"""Small, dependency-free contextual bandits for RL-0 policy selection.

RL-0 is deliberately *not* a deep RL agent. It chooses among a finite set of
existing supply-chain policies or parameter settings. This is the safest way to
add online learning to a system whose simulator is expensive and whose actions
must remain feasible.

Algorithms:

* epsilon-greedy;
* UCB1;
* sliding-window UCB (non-stationary rewards);
* Thompson sampling with Beta rewards in [0, 1];
* LinUCB with per-arm ridge regression.

All selectors share ``select(context) -> int`` and
``update(action, reward, context)``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np


class BanditError(ValueError):
    """Raised for malformed bandit inputs."""


class BanditPolicy:
    """Protocol-like base class; subclasses implement select/update."""

    name = "base"

    def select(self, context: Optional[np.ndarray] = None) -> int:
        raise NotImplementedError

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        raise NotImplementedError

    def scores(self) -> Dict[str, Any]:
        return {"name": self.name}


@dataclass
class EpsilonGreedy(BanditPolicy):
    n_actions: int
    epsilon: float = 0.1
    seed: int = 0
    name: str = "epsilon_greedy"
    _counts: np.ndarray = field(init=False, repr=False)
    _values: np.ndarray = field(init=False, repr=False)
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_actions < 2:
            raise BanditError("n_actions 至少为 2")
        if not 0.0 <= self.epsilon <= 1.0:
            raise BanditError("epsilon 必须在 [0, 1]")
        self._counts = np.zeros(self.n_actions, dtype=int)
        self._values = np.zeros(self.n_actions, dtype=float)
        self._rng = np.random.default_rng(self.seed)

    def select(self, context: Optional[np.ndarray] = None) -> int:
        if np.any(self._counts == 0):
            return int(np.flatnonzero(self._counts == 0)[0])
        if self._rng.random() < self.epsilon:
            return int(self._rng.integers(self.n_actions))
        return int(np.argmax(self._values))

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        self._counts[action] += 1
        n = self._counts[action]
        self._values[action] += (float(reward) - self._values[action]) / n


@dataclass
class UCB1(BanditPolicy):
    n_actions: int
    exploration: float = 1.0
    name: str = "ucb1"
    _counts: np.ndarray = field(init=False, repr=False)
    _values: np.ndarray = field(init=False, repr=False)
    _total: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_actions < 2:
            raise BanditError("n_actions 至少为 2")
        if self.exploration < 0:
            raise BanditError("exploration 不能为负")
        self._counts = np.zeros(self.n_actions, dtype=int)
        self._values = np.zeros(self.n_actions, dtype=float)

    def select(self, context: Optional[np.ndarray] = None) -> int:
        if np.any(self._counts == 0):
            return int(np.flatnonzero(self._counts == 0)[0])
        bonus = self.exploration * np.sqrt(
            np.log(max(1, self._total)) / self._counts
        )
        return int(np.argmax(self._values + bonus))

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        self._counts[action] += 1
        self._total += 1
        n = self._counts[action]
        self._values[action] += (float(reward) - self._values[action]) / n


@dataclass
class SlidingWindowUCB(BanditPolicy):
    """UCB on the last ``window`` observations; adapts to non-stationarity."""

    n_actions: int
    window: int = 50
    exploration: float = 1.0
    name: str = "sw_ucb"
    _history: List[tuple[int, float]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_actions < 2:
            raise BanditError("n_actions 至少为 2")
        if self.window < 1:
            raise BanditError("window 必须为正")
        if self.exploration < 0:
            raise BanditError("exploration 不能为负")

    def _stats(self) -> tuple[np.ndarray, np.ndarray, int]:
        counts = np.zeros(self.n_actions, dtype=int)
        sums = np.zeros(self.n_actions, dtype=float)
        for action, reward in self._history[-self.window :]:
            counts[action] += 1
            sums[action] += reward
        return counts, sums, len(self._history[-self.window :])

    def select(self, context: Optional[np.ndarray] = None) -> int:
        counts, sums, total = self._stats()
        if np.any(counts == 0):
            return int(np.flatnonzero(counts == 0)[0])
        means = sums / counts
        bonus = self.exploration * np.sqrt(
            np.log(max(1, total)) / counts
        )
        return int(np.argmax(means + bonus))

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        self._history.append((int(action), float(reward)))


@dataclass
class ThompsonSampling(BanditPolicy):
    """Beta-Bernoulli Thompson sampling with rewards clipped to [0, 1]."""

    n_actions: int
    seed: int = 0
    name: str = "thompson"
    _alpha: np.ndarray = field(init=False, repr=False)
    _beta: np.ndarray = field(init=False, repr=False)
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_actions < 2:
            raise BanditError("n_actions 至少为 2")
        self._alpha = np.ones(self.n_actions, dtype=float)
        self._beta = np.ones(self.n_actions, dtype=float)
        self._rng = np.random.default_rng(self.seed)

    def select(self, context: Optional[np.ndarray] = None) -> int:
        samples = self._rng.beta(self._alpha, self._beta)
        return int(np.argmax(samples))

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        clipped = float(np.clip(reward, 0.0, 1.0))
        self._alpha[action] += clipped
        self._beta[action] += 1.0 - clipped


@dataclass
class LinUCB(BanditPolicy):
    """Linear UCB with a shared context and per-arm ridge regression."""

    n_actions: int
    n_features: int
    alpha: float = 0.5
    ridge: float = 1.0
    name: str = "linucb"
    _a: List[np.ndarray] = field(init=False, repr=False)
    _b: List[np.ndarray] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.n_actions < 2:
            raise BanditError("n_actions 至少为 2")
        if self.n_features < 1:
            raise BanditError("n_features 必须为正")
        if self.alpha < 0:
            raise BanditError("alpha 不能为负")
        if self.ridge <= 0:
            raise BanditError("ridge 必须为正")
        self._a = [
            np.eye(self.n_features) * self.ridge for _ in range(self.n_actions)
        ]
        self._b = [np.zeros(self.n_features) for _ in range(self.n_actions)]

    def _context(self, context: Optional[np.ndarray]) -> np.ndarray:
        if context is None:
            return np.zeros(self.n_features, dtype=float)
        value = np.asarray(context, dtype=float).reshape(-1)
        if value.size != self.n_features:
            raise BanditError(
                f"context 维度应为 {self.n_features}，实际 {value.size}"
            )
        return value

    def select(self, context: Optional[np.ndarray] = None) -> int:
        x = self._context(context)
        scores = []
        for index in range(self.n_actions):
            inverse = np.linalg.solve(self._a[index], np.eye(self.n_features))
            theta = inverse @ self._b[index]
            mean = float(theta @ x)
            bonus = float(self.alpha * np.sqrt(max(0.0, x @ inverse @ x)))
            scores.append(mean + bonus)
        return int(np.argmax(scores))

    def update(
        self,
        action: int,
        reward: float,
        context: Optional[np.ndarray] = None,
    ) -> None:
        x = self._context(context)
        self._a[action] += np.outer(x, x)
        self._b[action] += float(reward) * x


def make_policy(
    name: str,
    n_actions: int,
    seed: int = 0,
    n_features: int = 1,
    **kwargs: Any,
) -> BanditPolicy:
    """Factory used by the online benchmark."""
    normalized = name.lower()
    if normalized in {"epsilon", "epsilon_greedy"}:
        return EpsilonGreedy(n_actions, seed=seed, **kwargs)
    if normalized == "ucb1":
        return UCB1(n_actions, **kwargs)
    if normalized in {"sw_ucb", "sliding_window"}:
        return SlidingWindowUCB(n_actions, **kwargs)
    if normalized in {"thompson", "ts"}:
        return ThompsonSampling(n_actions, seed=seed)
    if normalized == "linucb":
        return LinUCB(n_actions, n_features, **kwargs)
    raise BanditError(f"未知 bandit: {name}")
