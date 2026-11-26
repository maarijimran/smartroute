"""Confidentiality assessment and the cloud-permission decision.

Two separate questions are answered here and kept separate on purpose:

1. `PayloadGate.assess`  - DETECTION: is this payload confidential?
2. `decide_cloud`        - ENFORCEMENT: given that answer, may it leave the host?

The same `assess` code runs twice per request: once to build the eligible set and
once on the exact payload about to be dispatched (the final outbound gate). The
learned router never sees or influences either step.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..policy_config import PolicyConfig
from .scanner import Finding, ScanResult, mask

KIND_SYSTEM = "system"
KIND_CONVERSATION = "conversation"
KIND_PUBLIC_DOC = "public_doc"
KIND_CONFIDENTIAL_DOC = "confidential_doc"

LOCAL_ONLY = "local_only"
CLOUD_ALLOWED = "cloud_allowed"


@dataclass(frozen=True)
class Part:
    """One piece of the outbound payload, tagged with where it came from."""

    kind: str
    text: str


@dataclass
class Assessment:
    sensitive: bool
    scan_failed: bool
    entity_types: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    payload_sha256: str = ""
    masked_preview: str = ""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


_MASK_TAG = re.compile(r"\[[A-Z_]+\]")


def excerpt(masked: str, limit: int) -> str:
    """A short window of already-masked text, positioned so the first masked
    identifier is visible (an auditor wants to see where the identifier sat)."""
    if len(masked) <= limit:
        return masked
    tag = _MASK_TAG.search(masked)
    if tag is None or tag.end() <= limit:
        return masked[: limit - 1] + "…"
    start = max(0, tag.start() - limit // 2)
    window = masked[start : start + limit - 2]
    return "…" + window + ("…" if start + limit - 2 < len(masked) else "")


class PayloadGate:
    """Scans payload parts, caching by content hash so the final gate does not
    re-run a detector on bytes it has already scanned in this request."""

    def __init__(self, scanner, cfg: PolicyConfig):
        self.scanner = scanner
        self.cfg = cfg
        self._cache: dict[str, ScanResult] = {}

    def _scan(self, text: str) -> ScanResult:
        key = sha256_text(text)
        if key not in self._cache:
            self._cache[key] = self.scanner.scan(text)
        return self._cache[key]

    def _blocking(self, part: Part, findings: list[Finding]) -> list[Finding]:
        allowed = set(self.cfg.blocking_entity_types)
        out = [f for f in findings if f.type in allowed]
        if part.kind == KIND_PUBLIC_DOC and self.cfg.exempt_person_in_public_documents:
            out = [f for f in out if f.type != "PERSON"]
        return out

    def assess(self, parts: list[Part], *, explicit_label: bool = False, session_label: bool = False) -> Assessment:
        triggers: list[str] = []
        types: set[str] = set()
        failed = False
        preview = ""
        for part in parts:
            if part.kind == KIND_SYSTEM:
                # The gateway's own fixed instructions, never user content. Scanning them only
                # yields false positives: GLiNER reads "SmartRoute" as a person's name, which
                # made every request confidential. A caller-supplied system prompt is marked
                # KIND_CONVERSATION and is still scanned.
                continue
            if part.kind == KIND_CONFIDENTIAL_DOC and "confidential_document" not in triggers:
                triggers.append("confidential_document")
            result = self._scan(part.text)
            if result.failed:
                failed = True
                continue
            blocking = self._blocking(part, result.findings)
            if blocking:
                types.update(f.type for f in blocking)
            if part.kind == KIND_CONVERSATION:
                preview = mask(part.text, result.findings)  # last conversation part wins
        if types:
            triggers.append("pii_detected")
        if explicit_label:
            triggers.append("explicit_label")
        if session_label:
            triggers.append("session_label")
        if failed:
            triggers.append("scanner_failure")
            preview = "[preview withheld: scanner failure]"
        joined = "\n".join(p.text for p in parts)
        return Assessment(
            sensitive=bool(triggers),
            scan_failed=failed,
            entity_types=sorted(types),
            triggers=triggers,
            payload_sha256=sha256_text(joined),
            masked_preview=excerpt(preview, self.cfg.audit_preview_chars),
        )


@dataclass(frozen=True)
class CloudPermission:
    allowed: bool
    reason: str
    consent_used: bool = False


def user_may_send_confidential(user_override: bool | None, cfg: PolicyConfig) -> bool:
    """Per-user override set by the superadmin wins; otherwise the organisation default."""
    return cfg.allow_confidential_cloud_default if user_override is None else user_override


def decide_cloud(
    cfg: PolicyConfig,
    *,
    user_override: bool | None,
    privacy_mode: str,
    assessment: Assessment,
    consent: bool,
) -> CloudPermission:
    """May this payload be sent to ANY cloud model? Order matters: the strictest rule wins."""
    if not cfg.cloud_enabled:
        return CloudPermission(False, "institutional_policy")  # overrides user consent
    if privacy_mode != CLOUD_ALLOWED:
        return CloudPermission(False, "local_only_mode")  # independent of detector output
    if assessment.scan_failed:
        return CloudPermission(False, "scanner_failure")  # fail closed
    if not assessment.sensitive:
        return CloudPermission(True, "not_confidential")
    if not user_may_send_confidential(user_override, cfg):
        return CloudPermission(False, "confidential_not_permitted")
    if cfg.require_consent_for_confidential and not consent:
        return CloudPermission(False, "consent_required")
    return CloudPermission(True, "confidential_permitted", consent_used=consent)
