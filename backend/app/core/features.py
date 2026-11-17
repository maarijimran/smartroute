"""Context vector x for the router (research guide 6.4).

Layout: [standardised numeric features] + [binary features] + [constant] + [PCA embedding].

Two features describe the conversation: the size of the earlier context that is
sent (log_history_tokens) and whether the message is a follow-up. The benchmark
workload is single-turn, so the frozen router learns nothing about them; the
online bandit learns their weights from live, rated traffic.

Only the numeric block is standardised. The guide's sketch standardised the task
indicators and the constant too, which would turn the constant into zero and
remove the intercept; that is corrected here.

The scaler statistics and the PCA projection come from `artifacts/features.json`,
which `scripts/fit_features.py` fits on the TRAINING split only. Without that file
the extractor uses fixed default scaling and no embedding block, so the gateway
still runs (rules policy, cold-start bandit).
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading

import numpy as np

from ..config import get_settings
from .analysis import TASKS

log = logging.getLogger(__name__)

NUMERIC_NAMES = ["log_in_tokens", "log_out_tokens", "complexity", "local_load", "log_history_tokens"]
DEFAULT_MEAN = [6.0, 6.0, 0.40, 0.5, 3.0]
DEFAULT_STD = [1.5, 0.6, 0.20, 1.0, 2.5]
ARTIFACT_NAME = "features.json"


class FeatureExtractor:
    def __init__(self, artifact: dict | None = None, encoder=None):
        artifact = artifact or {}
        if artifact and len(artifact.get("numeric_mean", [])) != len(NUMERIC_NAMES):
            log.warning("features.json was fitted for an older feature layout; re-run scripts/fit_features.py")
            artifact = {}
        self.version = str(artifact.get("version", "default"))
        self.mean = np.array(artifact.get("numeric_mean", DEFAULT_MEAN), dtype=float)
        self.std = np.array(artifact.get("numeric_std", DEFAULT_STD), dtype=float)
        self.std[self.std < 1e-8] = 1.0
        self.pca_mean = np.array(artifact["pca_mean"], dtype=float) if "pca_mean" in artifact else None
        self.pca_components = (
            np.array(artifact["pca_components"], dtype=float) if "pca_components" in artifact else None
        )
        self.encoder = encoder if self.pca_components is not None else None
        self._lock = threading.Lock()

    @property
    def embedding_dim(self) -> int:
        return 0 if self.encoder is None else int(self.pca_components.shape[0])

    @property
    def dim(self) -> int:
        return len(NUMERIC_NAMES) + 2 + len(TASKS) + 1 + self.embedding_dim

    def names(self) -> list[str]:
        return (
            NUMERIC_NAMES
            + ["has_document", "follow_up"]
            + [f"task_{t}" for t in TASKS]
            + ["constant"]
            + [f"emb_{i}" for i in range(self.embedding_dim)]
        )

    def extract(
        self,
        *,
        prompt: str,
        in_tokens: int,
        est_out_tokens: int,
        has_document: bool,
        complexity: float,
        task: str,
        local_load: float,
        history_tokens: int = 0,
        follow_up: bool = False,
    ) -> np.ndarray:
        numeric = np.array(
            [math.log1p(in_tokens), math.log1p(est_out_tokens), complexity, local_load, math.log1p(history_tokens)],
            dtype=float,
        )
        numeric = (numeric - self.mean) / self.std
        binary = [float(has_document), float(follow_up)] + [float(task == t) for t in TASKS] + [1.0]
        parts = [numeric, np.array(binary, dtype=float)]
        if self.encoder is not None:
            with self._lock:
                emb = np.asarray(self.encoder.encode([prompt], normalize_embeddings=True))[0]
            parts.append(self.pca_components @ (emb - self.pca_mean))
        return np.concatenate(parts)


_extractor: FeatureExtractor | None = None


def get_extractor() -> FeatureExtractor:
    """Loads the artifact and, if enabled, the sentence encoder (server only)."""
    global _extractor
    if _extractor is None:
        settings = get_settings()
        artifact = None
        path = os.path.join(settings.artifacts_dir, ARTIFACT_NAME)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                artifact = json.load(fh)
        encoder = None
        if settings.embeddings_enabled and artifact and "pca_components" in artifact:
            from sentence_transformers import SentenceTransformer

            encoder = SentenceTransformer(settings.embedding_model)
        elif settings.embeddings_enabled:
            log.warning("Embeddings enabled but %s has no PCA projection; run scripts/fit_features.py", path)
        _extractor = FeatureExtractor(artifact, encoder)
    return _extractor


def set_extractor(extractor: FeatureExtractor | None) -> None:
    global _extractor
    _extractor = extractor
