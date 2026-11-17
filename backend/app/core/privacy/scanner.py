"""Local PII detection: regex patterns, plus Presidio and GLiNER when enabled.

Design rules (research guide 6.3, proposal 5d):
- Everything runs inside the trusted host. Nothing here calls a network service.
- The result is the UNION of all enabled detectors.
- Fail closed: if a detector that is enabled cannot load or crashes, the scan is
  reported as failed and the caller must treat the payload as confidential.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field

from ...config import Settings, get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Finding:
    type: str  # canonical type, see policy_config.ENTITY_TYPES
    start: int
    end: int
    source: str  # "regex" | "presidio" | "gliner"
    score: float = 1.0


@dataclass
class ScanResult:
    findings: list[Finding] = field(default_factory=list)
    failed: bool = False
    failure_reason: str | None = None

    @property
    def types(self) -> list[str]:
        return sorted({f.type for f in self.findings})


# --------------------------------------------------------------------------- regex

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Pakistani CNIC: 5-7-1 digits. The undashed form must start with a province digit 1-7,
# which excludes ISBN-13 numbers (they start with 978 or 979).
_CNIC_DASHED = re.compile(r"(?<!\d)\d{5}-\d{7}-\d(?!\d)")
# The lookarounds reject digits that are part of a longer number or a decimal
# (0.4210112345671, 4210112345671.5) but accept a sentence-ending full stop.
_CNIC_PLAIN = re.compile(r"(?<!\d)(?<!\d\.)[1-7]\d{12}(?!\d)(?!\.\d)")
_PK_PHONE = re.compile(r"(?<![\d+])(?:\+92|0092|0)[ -]?3\d{2}[ -]?\d{7}(?!\d)")
_INTL_PHONE = re.compile(r"(?<![\w+])\+\d{1,3}[ -]?(?:\(?\d{2,4}\)?[ -]?){2,4}\d{2,4}(?!\d)")
_CARD = re.compile(r"(?<![\d-])(?:\d{4}[ -]?){3}\d{1,7}(?![\d-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2} ?(?:[A-Z0-9]{4} ?){2,7}[A-Z0-9]{1,4}\b")
# A person name directly followed by a citation marker is a cited author, not a data subject.
_CITATION_AFTER = re.compile(r"^\s*(?:et al\b|(?:(?:and|&)\s+[A-Z][\w-]+\s*)?[,(\[]?\s*\(?(?:19|20)\d{2})")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def regex_findings(text: str) -> list[Finding]:
    out: list[Finding] = []
    for m in _EMAIL.finditer(text):
        out.append(Finding("EMAIL", m.start(), m.end(), "regex"))
    for pattern in (_CNIC_DASHED, _CNIC_PLAIN):
        for m in pattern.finditer(text):
            out.append(Finding("NATIONAL_ID", m.start(), m.end(), "regex"))
    for m in _PK_PHONE.finditer(text):
        out.append(Finding("PHONE", m.start(), m.end(), "regex"))
    for m in _INTL_PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 8 <= len(digits) <= 15:
            out.append(Finding("PHONE", m.start(), m.end(), "regex"))
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and digits[0] in "3456" and _luhn_ok(digits):
            out.append(Finding("CREDIT_CARD", m.start(), m.end(), "regex"))
    for m in _IBAN.finditer(text):
        if _iban_ok(m.group()):
            out.append(Finding("BANK_ACCOUNT", m.start(), m.end(), "regex"))
    return out


# ------------------------------------------------------------------- ML detectors

_PRESIDIO_MAP = {
    "PERSON": "PERSON",
    "EMAIL_ADDRESS": "EMAIL",
    "PHONE_NUMBER": "PHONE",
    "CREDIT_CARD": "CREDIT_CARD",
    "IBAN_CODE": "BANK_ACCOUNT",
    "US_BANK_NUMBER": "BANK_ACCOUNT",
    "US_SSN": "NATIONAL_ID",
    "US_PASSPORT": "NATIONAL_ID",
}
_GLINER_LABELS = {
    "person": "PERSON",
    "email": "EMAIL",
    "phone_number": "PHONE",
    "national_id": "NATIONAL_ID",
    "passport_number": "NATIONAL_ID",
    "bank_account_number": "BANK_ACCOUNT",
    "credit_card_number": "CREDIT_CARD",
    "street_address": "ADDRESS",
    "date_of_birth": "OTHER",
}
_GLINER_WINDOW, _GLINER_OVERLAP = 1200, 200


class ScannerUnavailable(RuntimeError):
    pass


class PrivacyScanner:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._presidio = None
        self._gliner = None

    # -- lazy loaders -------------------------------------------------------
    def _load_presidio(self):
        if self._presidio is None:
            with self._lock:
                if self._presidio is None:
                    from presidio_analyzer import AnalyzerEngine
                    from presidio_analyzer.nlp_engine import NlpEngineProvider

                    provider = NlpEngineProvider(
                        nlp_configuration={
                            "nlp_engine_name": "spacy",
                            "models": [{"lang_code": "en", "model_name": self.settings.pii_spacy_model}],
                        }
                    )
                    self._presidio = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        return self._presidio

    def _load_gliner(self):
        if self._gliner is None:
            with self._lock:
                if self._gliner is None:
                    from gliner import GLiNER

                    self._gliner = GLiNER.from_pretrained(self.settings.pii_gliner_model)
        return self._gliner

    def warm_up(self) -> None:
        """Load enabled detectors at startup so the first request is not slow and
        configuration errors surface immediately."""
        if self.settings.pii_presidio:
            self._load_presidio()
        if self.settings.pii_gliner:
            self._load_gliner()

    # -- detectors ----------------------------------------------------------
    def _presidio_findings(self, text: str) -> list[Finding]:
        analyzer = self._load_presidio()
        results = analyzer.analyze(
            text=text, language="en", entities=list(_PRESIDIO_MAP), score_threshold=0.5
        )
        return [
            Finding(_PRESIDIO_MAP[r.entity_type], r.start, r.end, "presidio", float(r.score))
            for r in results
            if r.entity_type in _PRESIDIO_MAP
        ]

    def _gliner_findings(self, text: str) -> list[Finding]:
        model = self._load_gliner()
        labels = list(_GLINER_LABELS)
        out: list[Finding] = []
        step = _GLINER_WINDOW - _GLINER_OVERLAP
        for offset in range(0, max(len(text), 1), step):
            window = text[offset : offset + _GLINER_WINDOW]
            if not window.strip():
                continue
            for ent in model.predict_entities(window, labels, threshold=self.settings.pii_gliner_threshold):
                canonical = _GLINER_LABELS.get(ent["label"])
                if canonical:
                    out.append(
                        Finding(canonical, offset + ent["start"], offset + ent["end"], "gliner", float(ent["score"]))
                    )
            if offset + _GLINER_WINDOW >= len(text):
                break
        return out

    # -- public API ---------------------------------------------------------
    def scan(self, text: str) -> ScanResult:
        if not text or not text.strip():
            return ScanResult()
        try:
            findings = regex_findings(text)
            if self.settings.pii_presidio:
                findings += self._presidio_findings(text)
            if self.settings.pii_gliner:
                findings += self._gliner_findings(text)
        except Exception as exc:  # fail closed on ANY detector problem
            log.exception("privacy scanner failure")
            return ScanResult(failed=True, failure_reason=f"{type(exc).__name__}: {exc}"[:200])
        findings = [f for f in findings if not _is_cited_author(text, f)]
        return ScanResult(findings=_dedupe(findings))


def _is_cited_author(text: str, f: Finding) -> bool:
    return f.type == "PERSON" and bool(_CITATION_AFTER.match(text[f.end : f.end + 40]))


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int, int]] = set()
    out = []
    for f in sorted(findings, key=lambda f: (f.start, f.end)):
        key = (f.type, f.start, f.end)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def mask(text: str, findings: list[Finding]) -> str:
    """Replace every detected span with its type, e.g. `[NATIONAL_ID]`."""
    out, cursor = [], 0
    for f in sorted(findings, key=lambda f: (f.start, -f.end)):
        if f.start < cursor:
            continue  # overlapping span already masked
        out.append(text[cursor : f.start])
        out.append(f"[{f.type}]")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out)


_scanner: PrivacyScanner | None = None


def get_scanner() -> PrivacyScanner:
    global _scanner
    if _scanner is None:
        _scanner = PrivacyScanner()
    return _scanner


def set_scanner(scanner) -> None:
    """Swap the scanner (tests, and the privacy suite's forced-failure cases)."""
    global _scanner
    _scanner = scanner
