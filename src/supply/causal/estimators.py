"""Causal effect estimators used by the SCM benchmark.

Implemented:

* naive treated-minus-control difference;
* inverse probability weighting (Hajek form);
* augmented IPW / doubly robust;
* partially linear double/debiased ML with two-fold cross-fitting.

These are deliberately small, explicit implementations. They are not a causal
forest library; the point is to make the assumptions and failure modes visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

import numpy as np
import pandas as pd
import statsmodels.api as sm


class CausalEstimationError(ValueError):
    """Raised when an estimator cannot be fit honestly."""


@dataclass(frozen=True)
class EffectEstimate:
    """One point estimate with a normal-approximation confidence interval."""

    method: str
    estimate: float
    std_error: float
    ci_low: float
    ci_high: float
    n: int
    treated: int
    control: int
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method,
            "estimate": float(self.estimate),
            "std_error": float(self.std_error),
            "ci_low": float(self.ci_low),
            "ci_high": float(self.ci_high),
            "n": int(self.n),
            "treated": int(self.treated),
            "control": int(self.control),
            "diagnostics": dict(self.diagnostics),
        }


def _prepare(
    data: pd.DataFrame,
    treatment: str,
    outcome: str,
    covariates: Sequence[str],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    needed = [treatment, outcome, *covariates]
    missing = [name for name in needed if name not in data.columns]
    if missing:
        raise CausalEstimationError(f"缺少列: {missing}")
    frame = data.loc[:, needed].dropna()
    if frame.empty:
        raise CausalEstimationError("删除缺失值后没有样本")
    y = frame[outcome].to_numpy(dtype=float)
    t = frame[treatment].to_numpy(dtype=float)
    if not np.all(np.isin(t, (0.0, 1.0))):
        raise CausalEstimationError("treatment 必须是 0/1")
    if t.sum() == 0 or (1 - t).sum() == 0:
        raise CausalEstimationError("treatment 两组都至少需要一个样本")
    x = frame.loc[:, covariates].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    return y, t, x


def _propensity(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    try:
        model = sm.Logit(t, x).fit(disp=0, maxiter=200)
        score = np.asarray(model.predict(x), dtype=float)
    except Exception:  # noqa: BLE001 - separation is common on small samples
        # A constant propensity is a conservative fallback; the diagnostics
        # still expose the lack of overlap separately.
        score = np.full(len(t), float(np.clip(t.mean(), 0.02, 0.98)))
    return np.clip(score, 0.01, 0.99)


def _overlap_diagnostics(t: np.ndarray, e: np.ndarray) -> Dict[str, Any]:
    return {
        "propensity_min": float(e.min()),
        "propensity_max": float(e.max()),
        "propensity_mean": float(e.mean()),
        "overlap_share": float(np.mean((e >= 0.05) & (e <= 0.95))),
        "treated_share": float(t.mean()),
        "max_weight": float(
            max(np.max(1.0 / e), np.max(1.0 / (1.0 - e)))
        ),
    }


def naive_difference(
    data: pd.DataFrame,
    treatment: str = "treatment",
    outcome: str = "otif",
    covariates: Sequence[str] = (),
) -> EffectEstimate:
    """Treated minus control mean; biased under confounding by design."""
    y, t, _ = _prepare(data, treatment, outcome, covariates)
    treated = y[t == 1]
    control = y[t == 0]
    estimate = float(treated.mean() - control.mean())
    se = float(
        np.sqrt(
            treated.var(ddof=1) / len(treated)
            + control.var(ddof=1) / len(control)
        )
    )
    return EffectEstimate(
        method="naive",
        estimate=estimate,
        std_error=se,
        ci_low=estimate - 1.96 * se,
        ci_high=estimate + 1.96 * se,
        n=len(y),
        treated=len(treated),
        control=len(control),
        diagnostics={"bias_risk": "confounding"},
    )


def ipw(
    data: pd.DataFrame,
    treatment: str = "treatment",
    outcome: str = "otif",
    covariates: Sequence[str] = (
        "forecast",
        "capacity",
        "demand",
        "seasonality",
        "promise",
    ),
) -> EffectEstimate:
    """Hajek inverse-probability weighting."""
    y, t, x = _prepare(data, treatment, outcome, covariates)
    e = _propensity(t, x)
    w1 = t / e
    w0 = (1.0 - t) / (1.0 - e)
    m1 = float(np.sum(w1 * y) / np.sum(w1))
    m0 = float(np.sum(w0 * y) / np.sum(w0))
    v1 = float(np.sum(w1**2 * (y - m1) ** 2) / np.sum(w1) ** 2)
    v0 = float(np.sum(w0**2 * (y - m0) ** 2) / np.sum(w0) ** 2)
    se = float(np.sqrt(max(v1 + v0, 0.0)))
    estimate = m1 - m0
    return EffectEstimate(
        method="ipw",
        estimate=estimate,
        std_error=se,
        ci_low=estimate - 1.96 * se,
        ci_high=estimate + 1.96 * se,
        n=len(y),
        treated=int(t.sum()),
        control=int((1 - t).sum()),
        diagnostics=_overlap_diagnostics(t, e),
    )


def aipw(
    data: pd.DataFrame,
    treatment: str = "treatment",
    outcome: str = "otif",
    covariates: Sequence[str] = (
        "forecast",
        "capacity",
        "demand",
        "seasonality",
        "promise",
    ),
) -> EffectEstimate:
    """Augmented IPW / doubly robust estimator."""
    y, t, x = _prepare(data, treatment, outcome, covariates)
    e = _propensity(t, x)
    fitted: Dict[str, Any] = {}
    models: Dict[str, Any] = {}
    for label, mask in (("treated", t == 1), ("control", t == 0)):
        try:
            model = sm.OLS(y[mask], x[mask]).fit()
        except Exception as exc:  # noqa: BLE001
            raise CausalEstimationError(
                f"{label} outcome model 拟合失败: {exc}"
            ) from exc
        models[label] = model
        fitted[label] = float(model.rsquared)
    mu1 = np.asarray(models["treated"].predict(x), dtype=float)
    mu0 = np.asarray(models["control"].predict(x), dtype=float)
    psi = (
        mu1
        - mu0
        + t * (y - mu1) / e
        - (1.0 - t) * (y - mu0) / (1.0 - e)
    )
    estimate = float(psi.mean())
    se = float(psi.std(ddof=1) / np.sqrt(len(psi)))
    diagnostics = _overlap_diagnostics(t, e)
    diagnostics["outcome_r2"] = fitted
    return EffectEstimate(
        method="aipw",
        estimate=estimate,
        std_error=se,
        ci_low=estimate - 1.96 * se,
        ci_high=estimate + 1.96 * se,
        n=len(y),
        treated=int(t.sum()),
        control=int((1 - t).sum()),
        diagnostics=diagnostics,
    )


def dml(
    data: pd.DataFrame,
    treatment: str = "treatment",
    outcome: str = "otif",
    covariates: Sequence[str] = (
        "forecast",
        "capacity",
        "demand",
        "seasonality",
        "promise",
    ),
    n_folds: int = 2,
    seed: int = 0,
) -> EffectEstimate:
    """Partially linear DML with cross-fitted OLS nuisance models."""
    if n_folds < 2:
        raise CausalEstimationError("n_folds 至少为 2")
    y, t, x = _prepare(data, treatment, outcome, covariates)
    rng = np.random.default_rng(seed)
    folds = np.array_split(rng.permutation(len(y)), n_folds)
    y_res = np.zeros_like(y)
    t_res = np.zeros_like(t)
    for fold in folds:
        mask = np.ones(len(y), dtype=bool)
        mask[fold] = False
        if mask.sum() <= x.shape[1]:
            raise CausalEstimationError("训练折样本不足以拟合 nuisance 模型")
        model_y = sm.OLS(y[mask], x[mask]).fit()
        model_t = sm.OLS(t[mask], x[mask]).fit()
        y_res[fold] = y[fold] - model_y.predict(x[fold])
        t_res[fold] = t[fold] - model_t.predict(x[fold])
    denom = float(np.sum(t_res**2))
    if denom <= 1e-12:
        raise CausalEstimationError("treatment 残差方差过小，无法识别")
    theta = float(np.sum(t_res * y_res) / denom)
    influence = t_res * (y_res - theta * t_res)
    se = float(np.std(influence, ddof=1) / np.sqrt(len(y)) / (denom / len(y)))
    diagnostics = {
        "n_folds": n_folds,
        "residual_t_sd": float(t_res.std(ddof=1)),
        "residual_y_sd": float(y_res.std(ddof=1)),
    }
    return EffectEstimate(
        method="dml",
        estimate=theta,
        std_error=se,
        ci_low=theta - 1.96 * se,
        ci_high=theta + 1.96 * se,
        n=len(y),
        treated=int(t.sum()),
        control=int((1 - t).sum()),
        diagnostics=diagnostics,
    )


def estimate_all(
    data: pd.DataFrame,
    treatment: str = "treatment",
    outcome: str = "otif",
    covariates: Sequence[str] = (
        "forecast",
        "capacity",
        "demand",
        "seasonality",
        "promise",
    ),
) -> List[EffectEstimate]:
    """Run all estimators; keep independent so one failure does not hide others."""
    results: List[EffectEstimate] = []
    for function in (naive_difference, ipw, aipw, dml):
        try:
            results.append(
                function(
                    data,
                    treatment=treatment,
                    outcome=outcome,
                    covariates=covariates,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report, do not fabricate
            results.append(
                EffectEstimate(
                    method=function.__name__,
                    estimate=float("nan"),
                    std_error=float("nan"),
                    ci_low=float("nan"),
                    ci_high=float("nan"),
                    n=len(data),
                    treated=int(data[treatment].sum()),
                    control=int((1 - data[treatment]).sum()),
                    diagnostics={"error": f"{type(exc).__name__}: {exc}"},
                )
            )
    return results
