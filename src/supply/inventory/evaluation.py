"""Evaluation split: history for parameter estimation, out-of-sample weeks to score.

Two forecast sources are supported:

* **seasonal naive** -- ``demand[t - 52]``, always available and transparent.
* **LightGBM backtest** -- if ``benchmarks/backtest_predictions.csv`` exists,
  each evaluation week is covered by exactly one rolling-origin fold, so the
  concatenated predictions are genuinely out-of-sample.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..forecasting.metrics import bias, wmape


@dataclass
class EvaluationSetup:
    weeks: pd.DatetimeIndex
    skus: list[str]
    demand: pd.DataFrame
    forecast: Dict[str, pd.DataFrame]
    history: pd.DataFrame
    history_weeks: int

    def forecast_accuracy(self) -> pd.DataFrame:
        rows = []
        for name, frame in self.forecast.items():
            actual = self.demand.to_numpy(dtype=float)
            pred = frame.to_numpy(dtype=float)
            rows.append(
                {
                    "forecast": name,
                    "wmape": wmape(actual.ravel(), pred.ravel()),
                    "bias": bias(actual.ravel(), pred.ravel()),
                    "units": float(actual.sum()),
                }
            )
        return pd.DataFrame(rows)

    def restrict(self, skus: list[str]) -> "EvaluationSetup":
        """Keep only SKUs with enough history for an inventory policy."""
        keep = [sku for sku in self.skus if sku in set(skus)]
        return EvaluationSetup(
            weeks=self.weeks,
            skus=keep,
            demand=self.demand[keep],
            forecast={name: frame[keep] for name, frame in self.forecast.items()},
            history=self.history,
            history_weeks=self.history_weeks,
        )


def seasonal_naive_matrix(demand: pd.DataFrame, seasonality: int = 52) -> pd.DataFrame:
    return demand.shift(seasonality)


def load_backtest_forecasts(
    path: str | Path,
    demand: pd.DataFrame,
    model: str = "lightgbm",
    fallback: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Pivot one model's rolling-origin predictions onto the evaluation grid.

    Folds are disjoint in time, so concatenating them yields one out-of-sample
    prediction per SKU-week. SKUs missing from a fold (ineligible history) fall
    back to the seasonal-naive path.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"找不到回测预测文件: {path}")
    raw = pd.read_csv(
        path,
        usecols=["model", "sku", "week", "pred"],
        dtype={"sku": "string"},
    )
    raw = raw[raw["model"] == model]
    if raw.empty:
        raise ValueError(f"回测文件中没有模型 {model} 的预测")
    raw["week"] = pd.to_datetime(raw["week"])
    raw["sku"] = raw["sku"].astype(str)
    raw = raw.drop_duplicates(subset=["sku", "week"], keep="last")

    pivot = raw.pivot(index="week", columns="sku", values="pred")
    pivot = pivot.reindex(index=demand.index, columns=demand.columns)
    pivot = pivot.astype(float).clip(lower=0.0)
    if fallback is not None:
        pivot = pivot.combine_first(fallback)
    return pivot.fillna(0.0)


def build_evaluation(
    panel: pd.DataFrame,
    eval_weeks: int = 52,
    history_weeks: int = 52,
    backtest_path: Optional[str | Path] = None,
    seasonality: int = 52,
) -> EvaluationSetup:
    frame = panel.copy()
    frame["week"] = pd.to_datetime(frame["week"])
    pivot = (
        frame.pivot(index="week", columns="sku", values="demand")
        .sort_index()
        .fillna(0.0)
    )
    pivot.columns = pd.Index([str(column) for column in pivot.columns], name="sku")
    if len(pivot) <= eval_weeks:
        raise ValueError(f"面板只有 {len(pivot)} 周，eval_weeks={eval_weeks} 过大")

    eval_frame = pivot.iloc[-eval_weeks:]
    history = pivot.iloc[:-eval_weeks].tail(history_weeks)
    if len(history) < seasonality:
        raise ValueError(
            f"估计窗口只有 {len(history)} 周，至少需要 {seasonality} 周"
        )

    fallback = seasonal_naive_matrix(pivot).reindex(eval_frame.index)
    forecasts = {"seasonal_naive": fallback.fillna(0.0)}
    if backtest_path:
        try:
            forecasts["lightgbm"] = load_backtest_forecasts(
                backtest_path, eval_frame, model="lightgbm", fallback=fallback
            )
        except (FileNotFoundError, ValueError):
            pass

    history_panel = (
        history.stack().rename("demand").reset_index()
    )
    # Re-attach price/description from the last observation per SKU.
    attributes = (
        frame.sort_values("week")
        .groupby("sku", as_index=False)
        .agg(
            description=("description", "last"),
            country=("country", "last"),
            avg_price=("avg_price", "last"),
        )
    )
    history_panel = history_panel.merge(attributes, on="sku", how="left")
    history_panel["week"] = pd.to_datetime(history_panel["week"])

    return EvaluationSetup(
        weeks=pd.DatetimeIndex(eval_frame.index),
        skus=[str(sku) for sku in eval_frame.columns],
        demand=eval_frame,
        forecast=forecasts,
        history=history_panel,
        history_weeks=len(history),
    )


def demand_weeks_since(frame: pd.DataFrame, eval_weeks: int) -> pd.DataFrame:
    """Convenience helper for the MILP window: last ``eval_weeks`` rows."""
    return frame.iloc[-eval_weeks:]
