"""Reproducible causal-estimator benchmark on the SCM.

The benchmark answers a narrow question: *given the SCM is the data-generating
process, which estimator recovers its known total effect under confounding?*
It is not evidence that the same estimate holds on the real UCI data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .estimators import estimate_all
from .scm import SupplyChainSCM, SupplyChainSCMConfig


@dataclass(frozen=True)
class CausalBenchmarkConfig:
    n_units: int = 3000
    n_replicates: int = 5
    confounding: float = 1.0
    seed: int = 7

    def __post_init__(self) -> None:
        if self.n_units < 100:
            raise ValueError("n_units 至少为 100")
        if self.n_replicates < 1:
            raise ValueError("n_replicates 至少为 1")
        if self.confounding < 0:
            raise ValueError("confounding 不能为负")


@dataclass
class CausalBenchmarkResult:
    truth: float
    rows: List[Dict[str, Any]]
    summary: pd.DataFrame
    config: CausalBenchmarkConfig
    dag: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "truth": float(self.truth),
            "config": {
                "n_units": self.config.n_units,
                "n_replicates": self.config.n_replicates,
                "confounding": self.config.confounding,
                "seed": self.config.seed,
            },
            "dag": dict(self.dag),
            "rows": list(self.rows),
            "summary": self.summary.to_dict("records"),
            "limitations": [
                "因果效应是 SCM 模型内的，不是 UCI 观测数据的真实因果效应。",
                "估计器依赖无未观测混杂/正确 nuisance 设定；基准只检验实现和诊断。",
            ],
        }


def run_estimator_benchmark(
    config: CausalBenchmarkConfig = CausalBenchmarkConfig(),
) -> CausalBenchmarkResult:
    """Run repeated SCM draws and summarise bias / RMSE / CI coverage."""
    rows: List[Dict[str, Any]] = []
    truth = SupplyChainSCMConfig(
        confounding=config.confounding
    ).true_ate
    for replicate in range(config.n_replicates):
        scm = SupplyChainSCM(
            SupplyChainSCMConfig(
                confounding=config.confounding,
                seed=config.seed + replicate,
            )
        )
        data = scm.sample_observational(config.n_units)
        for estimate in estimate_all(data):
            row = estimate.as_dict()
            row.update(
                {
                    "replicate": replicate,
                    "truth": truth,
                    "bias": estimate.estimate - truth,
                    "abs_bias": abs(estimate.estimate - truth),
                    "covered": bool(
                        np.isfinite(estimate.ci_low)
                        and np.isfinite(estimate.ci_high)
                        and estimate.ci_low <= truth <= estimate.ci_high
                    ),
                }
            )
            rows.append(row)
    frame = pd.DataFrame(rows)
    frame["width"] = frame["ci_high"] - frame["ci_low"]
    summary = (
        frame.groupby("method", as_index=False)
        .agg(
            mean_estimate=("estimate", "mean"),
            mean_bias=("bias", "mean"),
            mean_abs_bias=("abs_bias", "mean"),
            rmse=("bias", lambda values: float(np.sqrt(np.mean(np.square(values))))),
            coverage=("covered", "mean"),
            mean_ci_width=("width", "mean"),
        )
        .sort_values("mean_abs_bias")
        .reset_index(drop=True)
    )
    return CausalBenchmarkResult(
        truth=truth,
        rows=rows,
        summary=summary,
        config=config,
        dag=SupplyChainSCM().dag.as_dict(),
    )
