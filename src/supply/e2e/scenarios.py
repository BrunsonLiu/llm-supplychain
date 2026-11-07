"""Calibrated demand-scenario generation.

The existing ``build_demand_scenarios`` uses the last N weeks as *equally
weighted* scenarios. That is a good deployable baseline but it cannot express
cross-SKU dependence or a larger scenario set. This module adds two lightweight
frontier-adjacent generators:

* ``bootstrap``: resample historical weeks and add log-normal residual noise;
* ``gaussian_copula``: preserve the empirical rank correlation across SKUs.

Both return the existing ``ScenarioSet`` dataclass, so the CVaR solver does not
need to change. Weights are equal by construction; the class currently enforces
that.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .stochastic import (
    DemandScenario,
    FULFILLMENT_DCS,
    PROMISE_TIERS,
    ScenarioSet,
    build_demand_scenarios,
)


@dataclass(frozen=True)
class ScenarioConfig:
    """Configuration for the calibrated scenario generator."""

    method: str = "bootstrap"
    n_scenarios: int = 24
    lookback_weeks: int = 8
    residual_sd: float = 0.18
    seed: int = 42
    ridge: float = 1e-3

    def __post_init__(self) -> None:
        if self.method not in {"bootstrap", "gaussian_copula"}:
            raise ValueError("method 必须是 bootstrap 或 gaussian_copula")
        if self.n_scenarios < 2:
            raise ValueError("n_scenarios 至少为 2")
        if self.lookback_weeks < 2:
            raise ValueError("lookback_weeks 至少为 2")
        if self.residual_sd < 0:
            raise ValueError("residual_sd 不能为负")
        if self.ridge < 0:
            raise ValueError("ridge 不能为负")


def _rescale_to_total(values: np.ndarray, target: int) -> np.ndarray:
    """Scale non-negative integers to an exact total via largest remainder."""
    values = np.asarray(values, dtype=float)
    values = np.clip(values, 0.0, None)
    total = float(values.sum())
    if target <= 0:
        raise ValueError("target 必须为正")
    if total <= 0:
        return np.zeros_like(values, dtype=np.int64)
    raw = values * (float(target) / total)
    base = np.floor(raw).astype(np.int64)
    remainder = int(target - base.sum())
    if remainder > 0:
        order = np.argsort(-(raw - base), kind="stable")
        base[order[:remainder]] += 1
    elif remainder < 0:
        order = np.argsort(raw - base, kind="stable")
        for index in order[: -remainder]:
            if base[index] > 0:
                base[index] -= 1
    return base


def _serviceable_for(
    base: DemandScenario,
    demand: np.ndarray,
) -> np.ndarray:
    """Scale the base serviceable matrix to the new per-SKU demand."""
    base_demand = np.asarray(base.demand, dtype=float)
    service = np.asarray(base.serviceable, dtype=float).copy()
    ratio = np.divide(
        demand,
        base_demand,
        out=np.zeros_like(demand, dtype=float),
        where=base_demand > 0,
    )
    service = service * ratio[None, :]
    service = np.rint(service).astype(np.int64)
    return np.clip(service, 0, np.asarray(demand, dtype=np.int64)[None, :])


def _base_scenarios(
    clean: pd.DataFrame,
    skus: Sequence[str],
    week: pd.Timestamp | str,
    target_units: int,
    config: ScenarioConfig,
    dcs: Sequence[dict],
    promise_shares: Sequence[Tuple[int, float]],
) -> ScenarioSet:
    return build_demand_scenarios(
        clean,
        skus,
        week,
        target_units=target_units,
        lookback_weeks=config.lookback_weeks,
        dcs=dcs,
        promise_shares=promise_shares,
    )


def _bootstrap(
    base: ScenarioSet,
    config: ScenarioConfig,
) -> Tuple[List[DemandScenario], int]:
    rng = np.random.default_rng(config.seed)
    history = np.stack([scenario.demand for scenario in base.scenarios]).astype(float)
    scenarios: List[DemandScenario] = []
    for index in range(config.n_scenarios):
        source = base.scenarios[int(rng.integers(0, len(base.scenarios)))]
        noise = rng.normal(0.0, config.residual_sd, size=history.shape[1])
        demand = np.rint(np.clip(source.demand * np.exp(noise), 0, None)).astype(np.int64)
        demand = _rescale_to_total(demand, base.target_units)
        serviceable = _serviceable_for(source, demand)
        scenarios.append(
            DemandScenario(
                week=f"{base.weeks[0]}-bootstrap-{index:03d}",
                weight=1.0 / config.n_scenarios,
                demand=demand,
                serviceable=serviceable,
                raw_units=int(source.raw_units),
                scale=float(source.scale),
                history_lines=int(source.history_lines),
                active_skus=int((demand > 0).sum()),
            )
        )
    return scenarios, base.target_units


def _gaussian_copula(
    base: ScenarioSet,
    config: ScenarioConfig,
) -> Tuple[List[DemandScenario], int]:
    rng = np.random.default_rng(config.seed)
    history = np.stack([scenario.demand for scenario in base.scenarios]).astype(float)
    if history.shape[0] < 2:
        raise ValueError("copula 至少需要两个历史场景")
    # Standardise per SKU, add a small ridge for a stable Cholesky factor.
    means = history.mean(axis=0)
    stds = history.std(axis=0)
    stds = np.where(stds > 1e-9, stds, 1.0)
    standard = (history - means) / stds
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(standard, rowvar=False)
    if corr.ndim == 0:
        corr = np.array([[1.0]])
    corr = np.nan_to_num(corr, nan=0.0)
    corr = 0.5 * (corr + corr.T)
    corr = corr + np.eye(corr.shape[0]) * config.ridge
    eigenvalues = np.linalg.eigvalsh(corr)
    if eigenvalues.min() <= 1e-10:
        corr = np.eye(corr.shape[0])
    try:
        chol = np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        chol = np.eye(corr.shape[0])

    scenarios: List[DemandScenario] = []
    for index in range(config.n_scenarios):
        z = chol @ rng.normal(size=history.shape[1])
        u = np.clip(0.5 * (1.0 + _erf(z / np.sqrt(2.0))), 1e-4, 1.0 - 1e-4)
        demand = np.empty(history.shape[1], dtype=float)
        for sku in range(history.shape[1]):
            column = history[:, sku]
            demand[sku] = float(np.quantile(column, u[sku]))
        demand_int = _rescale_to_total(np.rint(demand), base.target_units)
        source = base.scenarios[int(rng.integers(0, len(base.scenarios)))]
        serviceable = _serviceable_for(source, demand_int)
        scenarios.append(
            DemandScenario(
                week=f"{base.weeks[0]}-copula-{index:03d}",
                weight=1.0 / config.n_scenarios,
                demand=demand_int,
                serviceable=serviceable,
                raw_units=int(source.raw_units),
                scale=float(source.scale),
                history_lines=int(source.history_lines),
                active_skus=int((demand_int > 0).sum()),
            )
        )
    return scenarios, base.target_units


def _erf(values: np.ndarray) -> np.ndarray:
    """Numerically stable erf via the standard library where possible."""
    try:
        from math import erf

        return np.vectorize(erf)(values)
    except Exception:  # pragma: no cover - vectorize is always available
        return np.tanh(values)


def build_calibrated_scenarios(
    clean: pd.DataFrame,
    skus: Iterable[str],
    week: pd.Timestamp | str,
    target_units: int,
    config: ScenarioConfig = ScenarioConfig(),
    dcs: Sequence[dict] = FULFILLMENT_DCS,
    promise_shares: Sequence[Tuple[int, float]] = PROMISE_TIERS,
) -> ScenarioSet:
    """Build a calibrated scenario set from historical weeks.

    Parameters mirror ``build_demand_scenarios`` so this is a drop-in upgrade.
    The output is marked with synthetic week labels, not real calendar weeks.
    """
    sku_names = tuple(str(sku) for sku in skus)
    if not sku_names:
        raise ValueError("SKU 列表不能为空")
    if target_units <= 0:
        raise ValueError("target_units 必须为正")
    base = _base_scenarios(
        clean,
        sku_names,
        week,
        target_units,
        config,
        dcs,
        promise_shares,
    )
    if config.method == "bootstrap":
        scenarios, target = _bootstrap(base, config)
    else:
        scenarios, target = _gaussian_copula(base, config)
    return ScenarioSet(
        scenarios=tuple(scenarios),
        sku_names=sku_names,
        dc_names=tuple(str(dc["name"]) for dc in dcs),
        target_units=int(target),
        promise_shares=tuple(
            (int(day), float(share)) for day, share in promise_shares
        ),
    )


def build_conformal_scenarios(
    forecast: pd.DataFrame,
    base: ScenarioSet,
    n_scenarios: int = 24,
    seed: int = 42,
    target_units: Optional[int] = None,
) -> ScenarioSet:
    """Build scenarios from conformal forecast intervals.

    ``forecast`` must contain one row per SKU with ``pred``, ``lower`` and
    ``upper``. Demand is sampled from a normal density centred at ``pred`` and
    clipped to the conformal interval, then rescaled to the target total. The
    serviceable DC shares come from a historical ``ScenarioSet``.

    This is a practical conformal scenario layer, not a full Conformal-DRO
    ambiguity set; the interval is used as a sampling truncation, not as a
    finite-sample certificate for the downstream optimization.
    """
    if n_scenarios < 2:
        raise ValueError("n_scenarios 至少为 2")
    needed = {"sku", "pred", "lower", "upper"}
    missing = sorted(needed - set(forecast.columns))
    if missing:
        raise ValueError(f"forecast 缺少列: {missing}")
    frame = forecast.loc[:, ["sku", "pred", "lower", "upper"]].copy()
    frame["sku"] = frame["sku"].astype(str)
    frame = frame.dropna()
    if frame.empty:
        raise ValueError("forecast 没有有效行")
    if frame["sku"].duplicated().any():
        raise ValueError("forecast 每个 SKU 只能有一行")
    if np.any(frame["upper"] < frame["lower"]):
        raise ValueError("forecast upper 不能小于 lower")
    target = int(base.target_units if target_units is None else target_units)
    if target <= 0:
        raise ValueError("target_units 必须为正")
    lookup = frame.set_index("sku")
    rng = np.random.default_rng(seed)
    base_mean = np.stack([scenario.demand for scenario in base.scenarios]).mean(axis=0)
    scenarios: List[DemandScenario] = []
    z = 1.6448536269514722  # two-sided 90% normal
    for index in range(n_scenarios):
        demand = np.zeros(len(base.sku_names), dtype=float)
        for sku_index, sku in enumerate(base.sku_names):
            if sku in lookup.index:
                row = lookup.loc[sku]
                low = max(0.0, float(row["lower"]))
                high = max(low, float(row["upper"]))
                pred = float(row["pred"])
                sigma = max((high - low) / (2.0 * z), 1e-6)
                demand[sku_index] = np.clip(rng.normal(pred, sigma), low, high)
            else:
                demand[sku_index] = float(base_mean[sku_index])
        if demand.sum() <= 0:
            demand = base_mean.copy()
        demand_int = _rescale_to_total(np.rint(demand), target)
        source = base.scenarios[int(rng.integers(0, len(base.scenarios)))]
        serviceable = _serviceable_for(source, demand_int)
        scenarios.append(
            DemandScenario(
                week=f"{base.weeks[0]}-conformal-{index:03d}",
                weight=1.0 / n_scenarios,
                demand=demand_int,
                serviceable=serviceable,
                raw_units=int(source.raw_units),
                scale=float(source.scale),
                history_lines=int(source.history_lines),
                active_skus=int((demand_int > 0).sum()),
            )
        )
    return ScenarioSet(
        scenarios=tuple(scenarios),
        sku_names=base.sku_names,
        dc_names=base.dc_names,
        target_units=target,
        promise_shares=base.promise_shares,
    )


def scenario_diagnostics(scenarios: ScenarioSet) -> dict:
    """Small diagnostic payload for the benchmark JSON."""
    demand = scenarios.demand
    weights = scenarios.weights
    mean = (demand * weights[:, None]).sum(axis=0)
    std = np.sqrt(((demand - mean[None, :]) ** 2 * weights[:, None]).sum(axis=0))
    return {
        "n_scenarios": int(demand.shape[0]),
        "n_skus": int(demand.shape[1]),
        "target_units": int(scenarios.target_units),
        "mean_units": float(mean.sum()),
        "mean_per_sku": [float(value) for value in mean],
        "sd_per_sku": [float(value) for value in std],
        "zero_share": float(np.mean(demand == 0)),
        "method_weeks": list(scenarios.weeks),
        "weights": [float(value) for value in weights],
        "weight_sum": float(weights.sum()),
    }
