"""Router v2 calibration: learn a new model's card from a few automatically scored questions.

The calibration bank (artifacts/calibration_bank.json, built on Kaggle by
scripts/build_calibration_bank.py) holds questions whose answers can be scored without
a judge: yes/no, extractive and unanswerable QASPER questions from the validation split,
multiple-choice and numeric questions from public benchmarks. Each item carries its
ready-to-send messages and its precomputed v2 features.

The runner asks the most informative questions first (irt.select_items), updates the
card after every batch and stops when the predicted-quality uncertainty is small enough,
at the question cap, or at the budget cap. Every model call is written to the cost
ledger and counted against the platform budget.

Privacy: the bank is public text, but the invariant "nothing flagged leaves the host"
still holds: items the privacy scanner flags are skipped for cloud models.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from ...config import get_settings
from ...models import Attempt, User, utcnow
from ..privacy.scanner import get_scanner
from ..providers import ChatRequest, ChatResult, ProviderError, build_provider
from .irt import ModelCard, select_items
from .router_v2 import STATUS_CALIBRATED, STATUS_CALIBRATING, RouterV2, get_router_v2, load_card, model_key, save_card

log = logging.getLogger(__name__)
BANK_NAME = "calibration_bank.json"
MAX_ATTEMPTS = 3
CALIBRATION_USER = "calibration"


@dataclass
class CalibrationSettings:
    batch: int = 10
    min_items: int = 20
    max_items: int = 60
    tolerance: float = 0.05  # mean standard deviation of predicted quality on the reference items
    budget_usd: float = 1.0
    max_output_tokens: int = 512


# ---------------------------------------------------------------------------- bank


def bank_path() -> str:
    return os.path.join(get_settings().artifacts_dir, BANK_NAME)


def load_bank(path: str | None = None) -> dict | None:
    path = path or bank_path()
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bank_compatible(bank: dict, router: RouterV2) -> bool:
    return list(bank.get("names", [])) == list(router.qm.names) and str(bank.get("feature_version")) == str(
        router.feature_version
    )


# ------------------------------------------------------------------------- scoring

_CHOICE = re.compile(r"\b(?:answer|option|choice)?\s*(?:is|:)?\s*\(?([A-E])\)?(?:[.)\s]|$)")
_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def score_item(item: dict, answer: str) -> float:
    """Automatic score in [0, 1] for one calibration answer."""
    kind = item.get("kind", "extractive")
    answer = answer or ""
    if kind == "mc":
        gold = str(item["golds"][0]).strip().upper()
        explicit = re.search(r"answer\s*(?:is|:)\s*\(?([A-E])\)?", answer, re.I)
        found = explicit.group(1).upper() if explicit else None
        if found is None:
            m = _CHOICE.search(answer.strip()[:40])
            found = m.group(1).upper() if m else None
        return float(found == gold)
    if kind == "numeric":
        numbers = [n.replace(",", "") for n in _NUMBER.findall(answer)]
        if not numbers:
            return 0.0
        try:
            got, gold = float(numbers[-1]), float(str(item["golds"][0]).replace(",", ""))
        except ValueError:
            return 0.0
        return float(abs(got - gold) <= 1e-6 + 1e-4 * abs(gold))
    from ...evaluation.scoring import score_answer

    return float(score_answer(answer, item["golds"], bool(item.get("unanswerable")), "doc_qa"))


# -------------------------------------------------------------------------- runner

_running: dict[str, threading.Thread] = {}
_running_lock = threading.Lock()


def is_running(tier: str) -> bool:
    with _running_lock:
        t = _running.get(tier)
        return t is not None and t.is_alive()


def start_in_background(tier: str, actor: User | None, settings: CalibrationSettings | None = None) -> bool:
    """Starts calibration of a tier's model in a thread. False if one is already running."""
    from ...db import SessionLocal

    with _running_lock:
        t = _running.get(tier)
        if t is not None and t.is_alive():
            return False

        def work():
            with SessionLocal() as db:
                try:
                    calibrate_tier(db, tier, actor.id if actor else None, settings)
                except Exception:
                    log.exception("calibration of the %s tier failed", tier)

        t = threading.Thread(target=work, name=f"calibrate-{tier}", daemon=True)
        _running[tier] = t
        t.start()
        return True


def calibrate_tier(db: Session, tier: str, actor_id: str | None = None,
                   settings: CalibrationSettings | None = None, bank: dict | None = None) -> dict:
    """Calibrates the model currently set for `tier`. Returns the calibration record that
    is also stored with the card (status, questions asked, uncertainty, cost, error)."""
    settings = settings or CalibrationSettings()
    router = get_router_v2()
    if router is None:
        raise CalibrationError("Router v2 has not been trained yet (artifacts/router_v2.json is missing).")
    bank = bank if bank is not None else load_bank()
    if bank is None:
        raise CalibrationError("The calibration bank is missing (artifacts/calibration_bank.json).")
    if not bank_compatible(bank, router):
        raise CalibrationError("The calibration bank was built for different features; rebuild it on Kaggle.")

    entry, spec, cred = _dispatch_target(db, tier)
    key = model_key(entry.vendor, entry.model_id)
    items = [it for it in bank["items"] if _allowed(it, spec.is_local)]
    if len(items) < settings.min_items:
        raise CalibrationError("Too few usable calibration questions in the bank.")
    X = np.array([it["xq"] for it in items], dtype=float)
    ref_idx = [i for i, it in enumerate(items) if it.get("reference")] or list(range(len(items)))
    x_ref = X[ref_idx]

    start_card, _ = load_card(db, router, key)
    if start_card.n == 0:
        start_card = ModelCard.prior(router.qm)
    record = {
        "tier": tier, "model_key": key, "router_version": router.version, "started_at": utcnow().isoformat(),
        "asked": 0, "scored": 0, "failed": 0, "cost_usd": 0.0, "uncertainty": None, "error": None,
        "target_uncertainty": settings.tolerance, "max_items": settings.max_items,
    }
    save_card(db, router, key, start_card, STATUS_CALIBRATING, dict(record))
    db.commit()

    provider = build_provider(spec, cred)
    card = start_card
    asked: set[int] = set()
    try:
        while len(asked) < settings.max_items:
            picks = select_items(router.qm, card, X, min(settings.batch, settings.max_items - len(asked)), exclude=asked)
            if not picks:
                break
            asked.update(picks)
            xs, ys = [], []
            for i in picks:
                if record["cost_usd"] >= settings.budget_usd:
                    raise _BudgetReached()
                result = _ask(provider, spec, items[i], settings)
                record["asked"] += 1
                if result is None:
                    record["failed"] += 1
                    continue
                cost = spec.cost_usd(result.in_tokens, result.out_tokens)
                record["cost_usd"] = round(record["cost_usd"] + cost, 6)
                db.add(Attempt(event_id=None, user_id=actor_id or CALIBRATION_USER, model_name=spec.name,
                               purpose="calibration", credential_scope=cred.scope if cred else "local",
                               status="ok", in_tokens=result.in_tokens, out_tokens=result.out_tokens,
                               cost_usd=cost, latency_ms=0.0))
                xs.append(X[i])
                ys.append(score_item(items[i], result.text))
            if record["asked"] >= 10 and record["failed"] > 0.3 * record["asked"]:
                raise CalibrationError(f"{record['failed']} of {record['asked']} calls failed; check the key, model ID and quota.")
            if xs:
                card = card.update(router.qm, np.array(xs), np.array(ys))
                record["scored"] += len(xs)
            record["uncertainty"] = round(card.quality_uncertainty(router.qm, x_ref), 4)
            save_card(db, router, key, card, STATUS_CALIBRATING, dict(record))
            db.commit()
            if record["scored"] >= settings.min_items and record["uncertainty"] < settings.tolerance:
                break
    except _BudgetReached:
        record["note"] = f"stopped at the budget cap of ${settings.budget_usd:.2f}"
    except CalibrationError as exc:
        record["error"] = str(exc)
    except Exception as exc:  # never leave a card stuck in "calibrating"
        log.exception("calibration failed")
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
    record["finished_at"] = utcnow().isoformat()
    ok = record["error"] is None and record["scored"] >= min(settings.min_items, 10)
    status = STATUS_CALIBRATED if ok else ("learning" if start_card.n else "uncalibrated")
    save_card(db, router, key, card if ok else start_card, status, dict(record))
    db.commit()
    return record


class CalibrationError(RuntimeError):
    pass


class _BudgetReached(Exception):
    pass


def _dispatch_target(db: Session, tier: str):
    """The tier's model, its dispatch spec and its key (the same lookup the pipeline uses)."""
    from .. import pipeline, tiers

    entry = tiers.slot(db, tier)
    if entry is None or not tiers.is_configured(entry):
        raise CalibrationError(f"The {tier} tier has no model yet.")
    if not entry.enabled:
        raise CalibrationError(f"The {tier} tier is switched off.")
    spec = pipeline.spec_from_entry(entry)
    cred = None
    from ..providers import VENDORS

    if VENDORS[entry.vendor].needs_key:
        cred = pipeline.resolve_credential(db, entry)
        if isinstance(cred, str):
            raise CalibrationError(f"No usable key for the {tier} tier ({cred}).")
    return entry, spec, cred


def _allowed(item: dict, is_local: bool) -> bool:
    """Cloud models only get items the privacy scanner does not flag."""
    if is_local:
        return True
    text = "\n".join(m.get("content", "") for m in item.get("messages", []))
    result = get_scanner().scan(text)
    return not result.failed and not result.findings


def _ask(provider, spec, item: dict, settings: CalibrationSettings) -> ChatResult | None:
    request = ChatRequest(model_id=spec.model_id, messages=item["messages"],
                          max_tokens=min(settings.max_output_tokens, spec.max_output_tokens) + spec.reasoning_overhead,
                          temperature=0.0, params=spec.params)
    for attempt in range(MAX_ATTEMPTS):
        try:
            return provider.complete(request)
        except ProviderError as exc:
            if exc.status not in (408, 429, 500, 502, 503, 504) or attempt == MAX_ATTEMPTS - 1:
                log.warning("calibration call failed: %s", exc)
                return None
            time.sleep(2 * (attempt + 1) ** 2)  # rate limits: 2 s, 8 s
        except Exception as exc:
            log.warning("calibration call failed: %s", exc)
            return None
    return None
