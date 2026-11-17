"""The 200-case synthetic privacy suite (proposal Table I) and its runner.

Every identifier is generated; no real person's data is used. The suite measures
two things separately, as the proposal requires:

  detector quality     precision / recall of "is this confidential?"
  enforcement          unauthorized dispatches: a payload reached a cloud model
                       although the expected decision was "blocked"

The runner always uses mock models, so it costs nothing and can capture the exact
payload that would have left the host. The detectors are whatever the environment
enables (regex only on a laptop; regex + Presidio + GLiNER on the server).
"""

from __future__ import annotations

import random

FIRST = ["Ayesha", "Bilal", "Hamza", "Fatima", "Usman", "Zainab", "Imran", "Sana", "Kamran", "Hina"]
LAST = ["Qureshi", "Siddiqui", "Farooqi", "Rizvi", "Chaudhry", "Mirza", "Baig", "Ansari", "Lodhi", "Soomro"]
STREETS = ["Shahrah-e-Faisal", "University Road", "Tariq Road", "Khayaban-e-Ittehad", "Rashid Minhas Road"]
ASKS = [
    "Summarise the attached complaint for the dean.",
    "Draft a short reply to this student.",
    "Explain what this record means in simple terms.",
    "Rewrite this note more formally.",
    "What should the department do next about this case?",
]
HARMLESS = [
    "Explain the difference between precision and recall.",
    "Summarise the main idea of contrastive learning in three sentences.",
    "What is a contextual bandit and how does it differ from supervised learning?",
    "Why does dropout reduce overfitting?",
    "Compare BM25 with dense retrieval for scientific question answering.",
]
LOOKALIKES = [
    "See arXiv:{a}.{b:05d} and arXiv:{c}.{d:05d} for the baselines.",
    "The DOI is 10.{a}/{b}.{c} and the paper appeared in {year}.",
    "ISBN 978{n10} is the reference textbook for this course.",
    "Accuracy rose from 0.{a} to 0.{c} after {b} training steps.",
    "Table {t} reports {a} {c} {b} tokens across the three corpora.",
    "We used Python 3.{t}.{u} with CUDA {t}.{u} on {b} examples.",
    "The model was trained for {b} steps with a learning rate of 0.000{t} and batch size {a}.",
    "Equation ({t}) gives a bound of {a}{c}{b} operations in the worst case.",
    "Sections {t}.{u} and {u}.{t} cover experiments run between {year} and 2025.",
    "The benchmark has {a}{c} questions over {b} documents, released on {year}-0{u}-1{t}.",
]


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def cnic(rng: random.Random, dashed: bool = True) -> str:
    body = rng.choice("1234567") + _digits(rng, 4), _digits(rng, 7), _digits(rng, 1)
    return "-".join(body) if dashed else "".join(body)


def pk_phone(rng: random.Random, style: int) -> str:
    code, rest = "3" + _digits(rng, 2), _digits(rng, 7)
    return [f"0{code}-{rest}", f"0{code}{rest}", f"+92 {code} {rest}", f"0092{code}{rest}"][style % 4]


def email(rng: random.Random) -> str:
    return f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}{rng.randint(1, 99)}@example.com"


def card(rng: random.Random) -> str:
    base = "4" + _digits(rng, 14)
    total = 0
    for i, ch in enumerate(base):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    number = base + str((10 - total % 10) % 10)
    return " ".join(number[i : i + 4] for i in range(0, 16, 4))


def iban(rng: random.Random) -> str:
    bban = rng.choice(["SCBL", "HABB", "MEZN", "UNIL"]) + _digits(rng, 16)
    numeric = "".join(str(int(c, 36)) for c in bban + "PK00")
    return f"PK{98 - int(numeric) % 97:02d}{bban}"


def person(rng: random.Random) -> str:
    return f"{rng.choice(FIRST)} {rng.choice(LAST)}"


def _case(cases: list, category: str, prompt: str, **kw) -> None:
    base = {
        "id": f"priv-{len(cases) + 1:03d}",
        "category": category,
        "prompt": prompt,
        "history": [],
        "document": None,
        "privacy_mode": "cloud_allowed",
        "consent": False,
        "user_permission": None,
        "policy": {},
        "scanner_failure": False,
        "local_available": True,
        "local_fails": False,
        "prior_consented_request": False,
        "truth_sensitive": False,
        "truth_types": [],
        "requires_ml": False,
        "detector_case": False,
        "expect_cloud_allowed": True,
    }
    base.update(kw)
    cases.append(base)


def build_suite(seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    cases: list[dict] = []

    # A. Direct identifiers in the prompt (60): 10 per type, including names.
    makers = [
        ("NATIONAL_ID", lambda i: f"The student's CNIC is {cnic(rng, dashed=i % 2 == 0)}."),
        ("PHONE", lambda i: f"Call the guardian on {pk_phone(rng, i)}."),
        ("EMAIL", lambda i: f"Send the transcript to {email(rng)}."),
        ("CREDIT_CARD", lambda i: f"The fee was charged to card {card(rng)}."),
        ("BANK_ACCOUNT", lambda i: f"Refund the deposit to IBAN {iban(rng)}."),
    ]
    for entity, make in makers:
        for i in range(10):
            _case(cases, "identifier", f"{rng.choice(ASKS)} {make(i)}", truth_sensitive=True,
                  truth_types=[entity], detector_case=True, expect_cloud_allowed=False)
    for i in range(10):
        who, street = person(rng), rng.choice(STREETS)
        text = (f"{who} of house {rng.randint(1, 400)}, {street}, Karachi failed the course and asked for a retake."
                if i % 2 else f"{who} has been reported for plagiarism in the final project.")
        _case(cases, "identifier", f"{rng.choice(ASKS)} {text}", truth_sensitive=True,
              truth_types=["PERSON"], requires_ml=True, detector_case=True, expect_cloud_allowed=False)

    # B. Benign lookalikes (40): numbers that resemble identifiers but are not.
    for i in range(40):
        text = LOOKALIKES[i % len(LOOKALIKES)].format(
            a=rng.randint(1000, 9999), b=rng.randint(10000, 99999), c=rng.randint(1000, 9999),
            d=rng.randint(1, 99999), t=rng.randint(2, 9), u=rng.randint(1, 9),
            year=rng.randint(2015, 2024), n10=_digits(rng, 10),
        )
        _case(cases, "lookalike", f"{rng.choice(HARMLESS)} {text}", detector_case=True)

    # C. Identifier in conversation history, harmless latest turn (20).
    for i in range(20):
        secret = [f"My CNIC is {cnic(rng)}.", f"My number is {pk_phone(rng, i)}.", f"Write to me at {email(rng)}."][i % 3]
        history = [{"role": "user", "content": f"Hello. {secret}"}, {"role": "assistant", "content": "Noted."}]
        _case(cases, "history", rng.choice(HARMLESS), history=history, truth_sensitive=True,
              detector_case=True, expect_cloud_allowed=False)

    # D. Documents (20): confidential label without identifiers; public label with identifiers.
    for i in range(10):
        body = "Internal examination committee minutes. " + "The committee reviewed moderation of the midterm marks. " * 12
        _case(cases, "document_label", "Summarise the decisions in this document.",
              document={"label": "confidential", "text": body}, truth_sensitive=True, expect_cloud_allowed=False)
    for i in range(10):
        body = ("Course feedback overview. " + "Students found the labs useful and well paced. " * 10
                + f"Contact the coordinator at {email(rng)} or {pk_phone(rng, i)} for the raw responses. "
                + "Overall satisfaction improved compared with last year. " * 6)
        _case(cases, "document_pii", "Who should be contacted for the raw responses?",
              document={"label": "public", "text": body}, truth_sensitive=True, detector_case=True,
              expect_cloud_allowed=False)

    # E. Consent and permission (30).
    def sensitive_prompt(i: int) -> str:
        return f"{rng.choice(ASKS)} The applicant's CNIC is {cnic(rng)}."

    for i in range(10):  # permitted by the superadmin + consent for this payload
        _case(cases, "consent_allowed", sensitive_prompt(i), truth_sensitive=True, user_permission=True, consent=True)
    for i in range(5):  # permitted, but no consent
        _case(cases, "consent_missing", sensitive_prompt(i), truth_sensitive=True, user_permission=True,
              expect_cloud_allowed=False)
    for i in range(5):  # consent without the superadmin's permission
        _case(cases, "consent_without_permission", sensitive_prompt(i), truth_sensitive=True,
              user_permission=False, consent=True, expect_cloud_allowed=False)
    for i in range(5):  # institutional prohibition beats permission and consent
        _case(cases, "institutional_prohibition", sensitive_prompt(i), truth_sensitive=True, user_permission=True,
              consent=True, policy={"cloud_enabled": False}, expect_cloud_allowed=False)
    for i in range(5):  # consent given on an earlier request does not carry over
        _case(cases, "changed_consent", sensitive_prompt(i), truth_sensitive=True, user_permission=True,
              prior_consented_request=True, expect_cloud_allowed=False)

    # F. Local-only mode, independent of detector output (10).
    for i in range(10):
        _case(cases, "local_only", HARMLESS[i % len(HARMLESS)], privacy_mode="local_only", expect_cloud_allowed=False)

    # G. Scanner failure fails closed (10).
    for i in range(10):
        _case(cases, "scanner_failure", HARMLESS[i % len(HARMLESS)], scanner_failure=True, expect_cloud_allowed=False)

    # H. Retries and abstention (10).
    for i in range(5):  # the local model fails: the retry must not escape to cloud
        _case(cases, "ineligible_retry", sensitive_prompt(i), truth_sensitive=True, local_fails=True,
              expect_cloud_allowed=False)
    for i in range(5):  # no local model at all: safe abstention
        _case(cases, "abstention", sensitive_prompt(i), truth_sensitive=True, local_available=False,
              expect_cloud_allowed=False)

    assert len(cases) == 200, len(cases)
    return cases


# --------------------------------------------------------------------- runner


class _FailingScanner:
    def scan(self, text):
        from ..core.privacy.scanner import ScanResult

        return ScanResult(failed=True, failure_reason="injected failure")


def run_suite(cases: list[dict]) -> dict:
    """Runs every case through the real pipeline against mock models. The caller
    must have pointed the app at a throwaway database (see scripts/run_privacy_suite.py)."""
    from sqlalchemy import delete, select

    from ..core import pipeline
    from ..core.cache import response_cache
    from ..core.documents import chunk_pages
    from ..core.policy_config import PolicyConfig, save_policy
    from ..core.privacy import scanner as scanner_module
    from ..core.providers.mock import MockProvider
    from ..db import SessionLocal
    from ..models import Document, DocumentChunk, ModelEntry, User
    from .workload import ensure_eval_user

    results = []
    with SessionLocal() as db:
        user = ensure_eval_user(db)
        admin = db.execute(select(User).where(User.role == "superadmin")).scalars().first()
        for case in cases:
            # Reset everything a previous case may have changed.
            save_policy(db, PolicyConfig(cache_enabled=False, **case["policy"]), admin)
            user.allow_confidential_cloud = case["user_permission"]
            for model in db.execute(select(ModelEntry)).scalars():
                model.enabled = model.vendor == "mock" and (case["local_available"] or not model.is_local)
                model.unhealthy_until = None
                model.params = {"mock": "fail"} if (model.is_local and case["local_fails"]) else {}
            db.execute(delete(DocumentChunk))
            db.execute(delete(Document))
            db.commit()
            response_cache.clear()
            scanner_module.set_scanner(_FailingScanner() if case["scanner_failure"] else None)

            document_ids = []
            if case["document"]:
                text = case["document"]["text"]
                doc = Document(user_id=user.id, filename="case.txt", label=case["document"]["label"], sha256=case["id"])
                db.add(doc)
                db.flush()
                db.add_all(
                    DocumentChunk(document_id=doc.id, idx=i, page=p, text=t)
                    for i, (p, t) in enumerate(chunk_pages([text]))
                )
                db.commit()
                document_ids = [doc.id]

            messages = case["history"] + [{"role": "user", "content": case["prompt"]}]

            def request(consent: bool):
                return pipeline.RouteRequest.for_user(
                    user, messages, source="eval", privacy_mode=case["privacy_mode"], consent=consent,
                    document_ids=document_ids, use_cache=False,
                    # Prefer a cloud model whenever one is eligible, so that any hole in
                    # enforcement shows up as a dispatch instead of being hidden by routing.
                    policy_override="fixed:strong" if case["expect_cloud_allowed"] else None,
                )

            if case["prior_consented_request"]:
                pipeline.run_to_completion(pipeline.prepare(db, request(True)))
            MockProvider.reset()
            plan = pipeline.prepare(db, request(case["consent"]))
            if not case["expect_cloud_allowed"] and plan.decision is not None:
                # Adversarial routing: steer blocked cases at the strongest cloud model too.
                cloud = [c for c in (r.candidate() for r in plan.routes.values()) if not c.is_local]
                if cloud:
                    plan.decision.arm = cloud[0].name
            permission_allowed = plan.permission.allowed
            detected = "pii_detected" in plan.assessment.triggers
            outcome = pipeline.run_to_completion(plan)
            dispatched = len(MockProvider.dispatched) > 0
            results.append(
                {
                    "id": case["id"],
                    "category": case["category"],
                    "status": outcome.status,
                    "model": outcome.model,
                    "detected_pii": detected,
                    "entity_types": plan.assessment.entity_types,
                    "cloud_permitted": permission_allowed,
                    "dispatched_to_cloud": dispatched,
                    # Enforcement failure: the gateway itself decided "blocked" and a
                    # payload still reached a cloud model. The target for this is zero.
                    "unauthorized_dispatch": dispatched and not permission_allowed,
                    # Detection miss: enforcement did what detection told it, but the
                    # detector did not recognise the content as confidential.
                    "leak_from_missed_detection": dispatched and permission_allowed
                    and not case["expect_cloud_allowed"],
                    "over_blocked": case["expect_cloud_allowed"] and not permission_allowed,
                }
            )
        scanner_module.set_scanner(None)
    return summarise(cases, results)


def summarise(cases: list[dict], results: list[dict]) -> dict:
    by_id = {r["id"]: r for r in results}
    detector = [c for c in cases if c["detector_case"]]

    def prf(subset):
        tp = sum(1 for c in subset if c["truth_sensitive"] and by_id[c["id"]]["detected_pii"])
        fn = sum(1 for c in subset if c["truth_sensitive"] and not by_id[c["id"]]["detected_pii"])
        fp = sum(1 for c in subset if not c["truth_sensitive"] and by_id[c["id"]]["detected_pii"])
        tn = sum(1 for c in subset if not c["truth_sensitive"] and not by_id[c["id"]]["detected_pii"])
        return {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }

    categories: dict[str, dict] = {}
    for c in cases:
        r = by_id[c["id"]]
        cat = categories.setdefault(
            c["category"], {"cases": 0, "unauthorized": 0, "leaked_undetected": 0, "over_blocked": 0}
        )
        cat["cases"] += 1
        cat["unauthorized"] += int(r["unauthorized_dispatch"])
        cat["leaked_undetected"] += int(r["leak_from_missed_detection"])
        cat["over_blocked"] += int(r["over_blocked"])
    return {
        "cases": len(cases),
        "enforcement": {
            "unauthorized_dispatches": sum(r["unauthorized_dispatch"] for r in results),
            "leaks_from_missed_detection": sum(r["leak_from_missed_detection"] for r in results),
            "expected_blocked": sum(1 for c in cases if not c["expect_cloud_allowed"]),
            "over_blocked": sum(r["over_blocked"] for r in results),
            "expected_allowed": sum(1 for c in cases if c["expect_cloud_allowed"]),
        },
        "detector": {
            "all": prf(detector),
            "pattern_detectable_only": prf([c for c in detector if not c["requires_ml"]]),
            "needs_ml_detector": prf([c for c in detector if c["requires_ml"]]),
        },
        "by_category": categories,
        "failures": [
            r for r in results if r["unauthorized_dispatch"] or r["leak_from_missed_detection"] or r["over_blocked"]
        ],
        "missed_detections": [
            c["id"] for c in detector if c["truth_sensitive"] and not by_id[c["id"]]["detected_pii"]
        ],
    }
