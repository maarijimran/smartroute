"""Detection (scanner) and enforcement (decide_cloud) are tested separately."""

import pytest

from app.config import Settings
from app.core.policy_config import PolicyConfig
from app.core.privacy.gate import (
    CLOUD_ALLOWED,
    KIND_CONFIDENTIAL_DOC,
    KIND_CONVERSATION,
    KIND_PUBLIC_DOC,
    KIND_SYSTEM,
    LOCAL_ONLY,
    Assessment,
    Part,
    PayloadGate,
    decide_cloud,
)
from app.core.privacy.scanner import Finding, PrivacyScanner, ScanResult, mask

scanner = PrivacyScanner(Settings(pii_presidio=False, pii_gliner=False))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("My CNIC is 42101-1234567-1 please check", "NATIONAL_ID"),
        ("cnic 4210112345671", "NATIONAL_ID"),
        ("The student's CNIC is 4210112345671.", "NATIONAL_ID"),  # sentence-ending full stop
        ("Call 03001234567.", "PHONE"),
        ("Call me on 0300-1234567 tomorrow", "PHONE"),
        ("Number: +92 300 1234567", "PHONE"),
        ("reach me at +44 20 7946 0958", "PHONE"),
        ("email ali.khan@example.com for details", "EMAIL"),
        ("card 4111 1111 1111 1111 exp 12/27", "CREDIT_CARD"),
        ("IBAN GB82 WEST 1234 5698 7654 32", "BANK_ACCOUNT"),
    ],
)
def test_detects_identifiers(text, expected):
    assert expected in scanner.scan(text).types


@pytest.mark.parametrize(
    "text",
    [
        "See arXiv:2305.05176 and doi 10.48550/arXiv.2406.18665 for details.",
        "ISBN 9780131103627 is the C book.",
        "The model has 7000000000000 parameters in total.",  # 13 digits but written as a count
        "Results improved from 0.8123 to 0.9345 between 2019 and 2023.",
        "Table 3 lists 1234 5678 9012 samples.",
        "Version 3.11.4 was released on 2024-10-07.",
        "The learning rate was 0.0003 with batch size 3200.",
        "The constant is 0.4210112345671 and the ratio 4210112345671.5 is unitless.",
    ],
)
def test_benign_lookalikes_are_not_flagged(text):
    types = scanner.scan(text).types
    # The 13-digit parameter count is the one accepted false positive of the
    # plain-CNIC pattern; everything else must be clean.
    if "7000000000000" in text:
        assert types in ([], ["NATIONAL_ID"])
    else:
        assert types == []


def test_mask_replaces_spans():
    text = "CNIC 42101-1234567-1 and mail a@b.co"
    masked = mask(text, scanner.scan(text).findings)
    assert "42101" not in masked and "a@b.co" not in masked
    assert "[NATIONAL_ID]" in masked and "[EMAIL]" in masked


def test_scanner_fails_closed_when_enabled_detector_is_missing():
    # Presidio is enabled but cannot load (missing package on the laptop, or a missing
    # spaCy model on the server): the scan must report failure instead of silently
    # falling back to regex only.
    broken = PrivacyScanner(
        Settings(pii_presidio=True, pii_gliner=False, pii_spacy_model="no_such_spacy_model")
    )
    result = broken.scan("perfectly harmless text")
    assert result.failed


class StubScanner:
    def __init__(self, findings=None, failed=False):
        self.findings, self.failed = findings or [], failed

    def scan(self, text):
        return ScanResult(findings=list(self.findings), failed=self.failed)


def test_cited_author_names_are_exempt_in_public_documents_only():
    cfg = PolicyConfig()
    person = StubScanner([Finding("PERSON", 0, 5, "stub")])
    gate = PayloadGate(person, cfg)
    assert not gate.assess([Part(KIND_PUBLIC_DOC, "Smith proposed it")]).sensitive
    assert gate.assess([Part(KIND_CONVERSATION, "Smith proposed it")]).sensitive
    strict = PolicyConfig(exempt_person_in_public_documents=False)
    assert PayloadGate(person, strict).assess([Part(KIND_PUBLIC_DOC, "Smith proposed it")]).sensitive


def test_gateway_system_prompt_is_not_scanned_but_caller_prompts_are():
    # GLiNER reads "SmartRoute" in the gateway's own prompt as a PERSON; that must not make
    # every request confidential. A caller's system prompt is conversation and still counts.
    person = StubScanner([Finding("PERSON", 8, 18, "stub")])
    gate = PayloadGate(person, PolicyConfig())
    assert not gate.assess([Part(KIND_SYSTEM, "You are SmartRoute, an assistant.")]).sensitive
    assert gate.assess([Part(KIND_CONVERSATION, "You are Ayesha Khan's assistant.")]).sensitive


def test_confidential_document_label_is_sensitive_without_any_identifier():
    gate = PayloadGate(StubScanner(), PolicyConfig())
    result = gate.assess([Part(KIND_CONFIDENTIAL_DOC, "internal grades sheet")])
    assert result.sensitive and result.triggers == ["confidential_document"]


def _assessment(sensitive=False, failed=False) -> Assessment:
    return Assessment(sensitive=sensitive or failed, scan_failed=failed)


def _decide(cfg=None, *, override=None, mode=CLOUD_ALLOWED, sensitive=False, failed=False, consent=False):
    return decide_cloud(
        cfg or PolicyConfig(),
        user_override=override,
        privacy_mode=mode,
        assessment=_assessment(sensitive, failed),
        consent=consent,
    )


def test_enforcement_matrix():
    assert _decide().allowed
    # Local-only removes cloud regardless of detector output.
    assert _decide(mode=LOCAL_ONLY).reason == "local_only_mode"
    # Scanner failure blocks cloud even if the user has every permission.
    assert _decide(failed=True, override=True, consent=True).reason == "scanner_failure"
    # Default organisation policy: confidential content may not go to cloud.
    assert _decide(sensitive=True, consent=True).reason == "confidential_not_permitted"
    # Permitted user still needs consent for this payload.
    assert _decide(sensitive=True, override=True).reason == "consent_required"
    allowed = _decide(sensitive=True, override=True, consent=True)
    assert allowed.allowed and allowed.consent_used
    # A per-user denial beats a permissive organisation default.
    permissive = PolicyConfig(allow_confidential_cloud_default=True)
    assert _decide(permissive, sensitive=True, override=False, consent=True).reason == "confidential_not_permitted"
    assert _decide(permissive, sensitive=True, consent=True).allowed
    # Institutional prohibition overrides user consent and permission.
    off = PolicyConfig(cloud_enabled=False, allow_confidential_cloud_default=True)
    assert _decide(off, sensitive=True, override=True, consent=True).reason == "institutional_policy"
    assert _decide(off).reason == "institutional_policy"
