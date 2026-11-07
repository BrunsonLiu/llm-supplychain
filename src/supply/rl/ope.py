"""Off-policy evaluation (OPE) for logged policy-selection data.

This is the bridge between the causal layer and RL: logged actions are only
usable if behaviour propensities are known (or estimated). The implementation
provides IPS and doubly robust (DR) estimates with a normal-approximation CI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import numpy as np
import pandas as pd


class OPEError(ValueError):
    """Raised for invalid logged data or target policies."""


@dataclass(frozen=True)
class PolicyValue:
    method: str
    value: float
    std_error: float
    ci_low: float
    ci_high: float
    n: int
    effective_sample_size: float
    diagnostics: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "value": float(self.value),
            "std_error": float(self.std_error),
            "ci_low": float(self.ci_low),
            "ci_high": float(self.ci_high),
            "n": int(self.n),
            "effective_sample_size": float(self.effective_sample_size),
            "diagnostics": dict(self.diagnostics),
        }


TargetPolicy = Callable[[pd.Series], np.ndarray]


def _prepare(
    data: pd.DataFrame,
    action: str,
    reward: str,
    propensity: str,
    n_actions: Optional[int],
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray, int]:
    needed = [action, reward, propensity]
    missing = [name for name in needed if name not in data.columns]
    if missing:
        raise OPEError(f"缺少列: {missing}")
    # Keep all columns: target policies may depend on context features.
    frame = data.dropna(subset=needed).reset_index(drop=True)
    if frame.empty:
        raise OPEError("删除缺失值后没有样本")
    actions = frame[action].to_numpy(dtype=int)
    rewards = frame[reward].to_numpy(dtype=float)
    behavior = frame[propensity].to_numpy(dtype=float)
    if np.any(behavior <= 0) or np.any(behavior > 1):
        raise OPEError("propensity 必须在 (0, 1]")
    if n_actions is None:
        n_actions = int(actions.max()) + 1
    if actions.min() < 0 or actions.max() >= n_actions:
        raise OPEError("action 超出范围")
    return frame, actions, rewards, behavior, int(n_actions)


def _target_matrix(
    data: pd.DataFrame,
    target: TargetPolicy,
    n_actions: int,
) -> np.ndarray:
    rows = []
    for _, row in data.iterrows():
        probs = np.asarray(target(row), dtype=float).reshape(-1)
        if probs.size != n_actions:
            raise OPEError("target policy 概率长度应等于动作数")
        if np.any(probs < 0) or not np.isclose(probs.sum(), 1.0, atol=1e-6):
            raise OPEError("target policy 必须是概率分布")
        rows.append(probs)
    return np.stack(rows)


def _summary(
    method: str,
    values: np.ndarray,
    weights: np.ndarray,
) -> PolicyValue:
    n = len(values)
    estimate = float(values.mean())
    se = float(values.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    effective = float(weights.sum() ** 2 / np.sum(weights**2)) if np.any(weights) else 0.0
    return PolicyValue(
        method=method,
        value=estimate,
        std_error=se,
        ci_low=estimate - 1.96 * se,
        ci_high=estimate + 1.96 * se,
        n=n,
        effective_sample_size=effective,
        diagnostics={
            "max_weight": float(weights.max()),
            "min_weight": float(weights.min()),
            "weight_sum": float(weights.sum()),
        },
    )


def ips(
    data: pd.DataFrame,
    target: TargetPolicy,
    action: str = "action",
    reward: str = "reward",
    propensity: str = "propensity",
    n_actions: Optional[int] = None,
    clip: Optional[float] = 20.0,
) -> PolicyValue:
    """Inverse propensity scoring for a target policy."""
    frame, actions, rewards, behavior, n_actions = _prepare(
        data, action, reward, propensity, n_actions
    )
    target_probs = _target_matrix(frame, target, n_actions)
    chosen = target_probs[np.arange(len(actions)), actions]
    weights = chosen / behavior
    if clip is not None:
        weights = np.minimum(weights, clip)
    values = weights * rewards
    return _summary("ips", values, weights)


def doubly_robust(
    data: pd.DataFrame,
    target: TargetPolicy,
    q_hat: np.ndarray,
    action: str = "action",
    reward: str = "reward",
    propensity: str = "propensity",
    n_actions: Optional[int] = None,
    clip: Optional[float] = 20.0,
) -> PolicyValue:
    """Doubly robust OPE with a model-based Q-hat baseline."""
    frame, actions, rewards, behavior, n_actions = _prepare(
        data, action, reward, propensity, n_actions
    )
    q_hat = np.asarray(q_hat, dtype=float)
    if q_hat.shape != (len(actions), n_actions):
        raise OPEError("q_hat 形状应为 (n, n_actions)")
    target_probs = _target_matrix(frame, target, n_actions)
    chosen = target_probs[np.arange(len(actions)), actions]
    weights = chosen / behavior
    if clip is not None:
        weights = np.minimum(weights, clip)
    baseline = np.sum(target_probs * q_hat, axis=1)
    correction = weights * (rewards - q_hat[np.arange(len(actions)), actions])
    values = baseline + correction
    return _summary("doubly_robust", values, weights)
