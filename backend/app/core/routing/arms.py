"""Per-model ridge regressors ("arms") shared by the frozen router and the bandits."""

from __future__ import annotations

import numpy as np


class RidgeArm:
    """Online ridge regression: theta = A^-1 b, with A = lam*I + sum(x x^T)."""

    def __init__(self, d: int, lam: float = 1.0):
        self.d = d
        self.lam = lam
        self.A = lam * np.eye(d)
        self.b = np.zeros(d)
        self.n = 0

    def theta(self) -> np.ndarray:
        return np.linalg.solve(self.A, self.b)

    def predict(self, x: np.ndarray) -> float:
        return float(self.theta() @ x)

    def uncertainty(self, x: np.ndarray) -> float:
        """sqrt(x^T A^-1 x): large when this arm has seen few contexts like x."""
        return float(np.sqrt(max(x @ np.linalg.solve(self.A, x), 0.0)))

    def update(self, x: np.ndarray, y: float, gamma: float = 1.0) -> None:
        """gamma < 1 forgets old data (ParetoBandit): the effective memory is about
        1 / (1 - gamma) observations, which lets the arm track drifting endpoints."""
        if gamma < 1.0:
            self.A = gamma * self.A + (1 - gamma) * self.lam * np.eye(self.d)
            self.b = gamma * self.b
        self.A += np.outer(x, x)
        self.b += y * x
        self.n += 1

    def to_json(self) -> dict:
        return {"A": self.A.tolist(), "b": self.b.tolist(), "n": self.n}

    @classmethod
    def from_json(cls, data: dict, lam: float) -> "RidgeArm":
        b = np.array(data["b"], dtype=float)
        arm = cls(len(b), lam)
        arm.A = np.array(data["A"], dtype=float)
        arm.b = b
        arm.n = int(data.get("n", 0))
        return arm


class ArmSet:
    """All arms of one learner plus the counters the exploration schedule needs."""

    def __init__(self, d: int, lam: float = 1.0, feature_version: str = "default"):
        self.d = d
        self.lam = lam
        self.feature_version = feature_version
        self.arms: dict[str, RidgeArm] = {}
        self.n_scored = 0

    def arm(self, name: str) -> RidgeArm:
        if name not in self.arms:
            self.arms[name] = RidgeArm(self.d, self.lam)
        return self.arms[name]

    def to_json(self) -> dict:
        return {
            "d": self.d,
            "lam": self.lam,
            "feature_version": self.feature_version,
            "n_scored": self.n_scored,
            "arms": {name: arm.to_json() for name, arm in self.arms.items()},
        }

    @classmethod
    def from_json(cls, data: dict) -> "ArmSet":
        s = cls(int(data["d"]), float(data.get("lam", 1.0)), str(data.get("feature_version", "default")))
        s.n_scored = int(data.get("n_scored", 0))
        s.arms = {name: RidgeArm.from_json(arm, s.lam) for name, arm in data.get("arms", {}).items()}
        return s

    def copy(self) -> "ArmSet":
        return ArmSet.from_json(self.to_json())
