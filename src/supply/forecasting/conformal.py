"""Split / Mondrian conformal calibration for weekly demand forecasts.

The backtest already produces out-of-sample rows with ``actual``, ``pred`` and a
per-SKU ``scale``. This module turns those residuals into finite-sample intervals
with an explicit calibration/test time split.

Important limitation: exchangeability is only approximate for time series. We
report empirical coverage and width; we do not claim an unconditional guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


class ConformalError(ValueError):
    """Raised for invalid calibration data or configuration."""


@dataclass(frozen=True)
class ConformalConfig:
    """Configuration for split/Mondrian conformal calibration."""

    alpha: float = 0.1
    method: str = "mondrian"
    min_samples: int = 80
    min_per_sku: int = 20
    n_buckets: int = 4
    horizon: int = 1
    model: Optional[str] = None

    def __post_init__(self) -> None:
        if not 0.0 < self.alpha < 1.0:
            raise ValueError("alpha 必须在 (0, 1)")
        if self.method not in {"global", "mondrian", "per_sku"}:
            raise ValueError("method 必须是 global/mondrian/per_sku")
        if self.min_samples < 10:
            raise ValueError("min_samples 至少为 10")
        if self.min_per_sku < 5:
            raise ValueError("min_per_sku 至少为 5")
        if self.n_buckets < 2:
            raise ValueError("n_buckets 至少为 2")
        if self.horizon < 1:
            raise ValueError("horizon 必须为正")


@dataclass(frozen=True)
class ConformalInterval:
    lower: float
    upper: float
    width: float
    q: float
    method: str
    bucket: Optional[int] = None
    sku: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "lower": float(self.lower),
            "upper": float(self.upper),
            "width": float(self.width),
            "q": float(self.q),
            "method": self.method,
            "bucket": None if self.bucket is None else int(self.bucket),
            "sku": self.sku,
        }


@dataclass
class ConformalCalibrator:
    config: ConformalConfig
    target_coverage: float
    q_global: float
    bucket_edges: np.ndarray
    q_buckets: Dict[int, float]
    q_skus: Dict[str, float]
    n_calibration: int
    calibration_start: str
    calibration_end: str
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def _bucket(self, pred: float) -> int:
        if len(self.bucket_edges) == 0:
            return 0
        return int(np.searchsorted(self.bucket_edges, float(pred), side="right"))

    def _q_for(self, pred: float, sku: Optional[str]) -> tuple[float, str, Optional[int]]:
        if sku is not None and sku in self.q_skus:
            return self.q_skus[sku], "per_sku", None
        bucket = self._bucket(pred)
        if bucket in self.q_buckets:
            return self.q_buckets[bucket], "mondrian", bucket
        return self.q_global, "global", None

    def interval(
        self,
        pred: float,
        sku: Optional[str] = None,
        scale: Optional[float] = None,
    ) -> ConformalInterval:
        """Build one interval; ``scale`` defaults to 1.0."""
        q, method, bucket = self._q_for(float(pred), sku)
        scale_value = 1.0 if scale is None or not np.isfinite(scale) else max(float(scale), 1e-9)
        lower = max(0.0, float(pred) - q * scale_value)
        upper = max(lower, float(pred) + q * scale_value)
        return ConformalInterval(
            lower=lower,
            upper=upper,
            width=upper - lower,
            q=q,
            method=method,
            bucket=bucket,
            sku=None if sku is None else str(sku),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "alpha": float(self.config.alpha),
            "target_coverage": float(self.target_coverage),
            "method": self.config.method,
            "q_global": float(self.q_global),
            "bucket_edges": [float(value) for value in self.bucket_edges],
            "q_buckets": {str(key): float(value) for key, value in self.q_buckets.items()},
            "q_skus": {str(key): float(value) for key, value in self.q_skus.items()},
            "n_calibration": int(self.n_calibration),
            "calibration_start": self.calibration_start,
            "calibration_end": self.calibration_end,
            "diagnostics": dict(self.diagnostics),
        }


def _normalise(predictions: pd.DataFrame, config: ConformalConfig) -> pd.DataFrame:
    required = {"sku", "week", "actual", "pred"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ConformalError(f"预测表缺少列: {missing}")
    frame = predictions.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    frame["sku"] = frame["sku"].astype(str)
    frame["actual"] = pd.to_numeric(frame["actual"], errors="coerce")
    frame["pred"] = pd.to_numeric(frame["pred"], errors="coerce")
    frame = frame.dropna(subset=["actual", "pred", "week", "sku"])
    if "scale" not in frame.columns:
        frame["scale"] = 1.0
    frame["scale"] = pd.to_numeric(frame["scale"], errors="coerce").fillna(1.0)
    frame["scale"] = np.where(frame["scale"] > 0, frame["scale"], 1.0)
    if "horizon" in frame.columns:
        frame = frame.loc[frame["horizon"].astype(int) == int(config.horizon)]
    if config.model is not None and "model" in frame.columns:
        frame = frame.loc[frame["model"].astype(str) == str(config.model)]
    if frame.empty:
        raise ConformalError("筛选后没有可用于校准的预测行")
    return frame


def _quantile(values: np.ndarray, coverage: float) -> float:
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        raise ConformalError("空残差无法取分位数")
    # Split-conformal finite-sample rank; clip because finite samples can push
    # the exact rank slightly above 1.
    rank = min(1.0, float(np.ceil((values.size + 1) * coverage) / values.size))
    return float(np.quantile(values, rank, method="higher"))


def fit_conformal(
    predictions: pd.DataFrame,
    target_week: pd.Timestamp | str,
    config: ConformalConfig = ConformalConfig(),
) -> ConformalCalibrator:
    """Fit on rows strictly before ``target_week``."""
    frame = _normalise(predictions, config)
    target = pd.Timestamp(target_week)
    calibration = frame.loc[frame["week"] < target].copy()
    if len(calibration) < config.min_samples:
        raise ConformalError(
            f"校准样本不足: {len(calibration)} < {config.min_samples}"
        )
    scores = (
        (calibration["actual"] - calibration["pred"]).abs()
        / calibration["scale"].astype(float)
    ).to_numpy(dtype=float)
    q_global = _quantile(scores, 1.0 - config.alpha)

    bucket_edges = np.array([], dtype=float)
    q_buckets: Dict[int, float] = {}
    if config.method == "mondrian":
        unique = np.unique(calibration["pred"].to_numpy(dtype=float))
        if unique.size >= config.n_buckets:
            edges = np.quantile(
                unique,
                np.linspace(0, 1, config.n_buckets + 1)[1:-1],
            )
            bucket_edges = np.unique(edges)
        calibration["_bucket"] = np.searchsorted(
            bucket_edges, calibration["pred"].to_numpy(dtype=float), side="right"
        )
        for bucket, group in calibration.groupby("_bucket"):
            if len(group) >= config.min_per_sku:
                q_buckets[int(bucket)] = _quantile(
                    (
                        (group["actual"] - group["pred"]).abs()
                        / group["scale"].astype(float)
                    ).to_numpy(dtype=float),
                    1.0 - config.alpha,
                )

    q_skus: Dict[str, float] = {}
    if config.method in {"per_sku", "mondrian"}:
        for sku, group in calibration.groupby("sku"):
            if len(group) >= config.min_per_sku:
                q_skus[str(sku)] = _quantile(
                    (
                        (group["actual"] - group["pred"]).abs()
                        / group["scale"].astype(float)
                    ).to_numpy(dtype=float),
                    1.0 - config.alpha,
                )

    return ConformalCalibrator(
        config=config,
        target_coverage=1.0 - config.alpha,
        q_global=q_global,
        bucket_edges=bucket_edges,
        q_buckets=q_buckets,
        q_skus=q_skus,
        n_calibration=int(len(calibration)),
        calibration_start=str(calibration["week"].min().date()),
        calibration_end=str(calibration["week"].max().date()),
        diagnostics={
            "n_skus": int(calibration["sku"].nunique()),
            "score_mean": float(scores.mean()),
            "score_p90": float(np.quantile(scores, 0.9)),
            "method": config.method,
        },
    )


def evaluate_conformal(
    predictions: pd.DataFrame,
    calibrator: ConformalCalibrator,
    start_week: pd.Timestamp | str,
    end_week: Optional[pd.Timestamp | str] = None,
) -> Dict[str, Any]:
    """Empirical coverage/width on the test period (no fitting)."""
    frame = predictions.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    if calibrator.config.model is not None and "model" in frame.columns:
        frame = frame.loc[
            frame["model"].astype(str) == str(calibrator.config.model)
        ]
    if "horizon" in frame.columns:
        frame = frame.loc[
            frame["horizon"].astype(int) == int(calibrator.config.horizon)
        ]
    start = pd.Timestamp(start_week)
    mask = frame["week"] >= start
    if end_week is not None:
        mask &= frame["week"] <= pd.Timestamp(end_week)
    frame = frame.loc[mask].copy()
    if frame.empty:
        raise ConformalError("测试期没有预测行")
    if "scale" not in frame.columns:
        frame["scale"] = 1.0
    frame["scale"] = pd.to_numeric(frame["scale"], errors="coerce").fillna(1.0)
    rows = []
    for row in frame.itertuples(index=False):
        interval = calibrator.interval(
            float(row.pred),
            sku=str(row.sku),
            scale=float(row.scale),
        )
        actual = float(row.actual)
        rows.append(
            {
                "week": row.week,
                "sku": str(row.sku),
                "actual": actual,
                "pred": float(row.pred),
                "lower": interval.lower,
                "upper": interval.upper,
                "covered": bool(interval.lower <= actual <= interval.upper),
                "width": interval.width,
                "method": interval.method,
            }
        )
    detail = pd.DataFrame(rows)
    overall = {
        "n": int(len(detail)),
        "target_coverage": float(calibrator.target_coverage),
        "empirical_coverage": float(detail["covered"].mean()),
        "mean_width": float(detail["width"].mean()),
        "median_width": float(detail["width"].median()),
        "coverage_gap": float(detail["covered"].mean() - calibrator.target_coverage),
        "by_week": [
            {
                "week": str(pd.Timestamp(week).date()),
                "n": int(len(group)),
                "coverage": float(group["covered"].mean()),
                "mean_width": float(group["width"].mean()),
            }
            for week, group in detail.groupby("week")
        ],
    }
    return {"overall": overall, "detail": detail.to_dict("records")}
