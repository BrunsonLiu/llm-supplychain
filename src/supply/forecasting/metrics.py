"""Forecast evaluation metrics: WMAPE, bias, MAE, RMSE, RMSSE."""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd


def wmape(actual: Sequence[float], pred: Sequence[float]) -> float:
    actual_arr = np.asarray(actual, dtype=float)
    pred_arr = np.asarray(pred, dtype=float)
    denominator = np.abs(actual_arr).sum()
    if denominator == 0:
        return 0.0 if np.abs(pred_arr).sum() == 0 else float("inf")
    return float(np.abs(actual_arr - pred_arr).sum() / denominator)


def bias(actual: Sequence[float], pred: Sequence[float]) -> float:
    actual_arr = np.asarray(actual, dtype=float)
    pred_arr = np.asarray(pred, dtype=float)
    denominator = np.abs(actual_arr).sum()
    if denominator == 0:
        return 0.0
    return float((pred_arr - actual_arr).sum() / denominator)


def mae(actual: Sequence[float], pred: Sequence[float]) -> float:
    return float(np.mean(np.abs(np.asarray(pred, float) - np.asarray(actual, float))))


def rmse(actual: Sequence[float], pred: Sequence[float]) -> float:
    err = np.asarray(pred, float) - np.asarray(actual, float)
    return float(np.sqrt(np.mean(err**2)))


def rmsse_scale(history: Sequence[float], seasonality: int = 1) -> float:
    """Per-series denominator for RMSSE (M5 convention).

    Uses the seasonal-naive in-sample MSE; falls back to the series variance
    when the seasonal difference is degenerate.
    """
    values = np.asarray(history, dtype=float)
    if values.size == 0:
        return 1.0
    if values.size > seasonality:
        scale = float(np.mean((values[seasonality:] - values[:-seasonality]) ** 2))
    else:
        scale = float(np.var(values))
    if not np.isfinite(scale) or scale <= 0:
        scale = float(np.mean(values**2))
    return max(scale, 1.0)


def horizon_bucket(horizon: int) -> str:
    if horizon <= 4:
        return "1-4"
    if horizon <= 8:
        return "5-8"
    if horizon <= 13:
        return "9-13"
    if horizon <= 26:
        return "14-26"
    return "27+"


def add_error_columns(predictions: pd.DataFrame) -> pd.DataFrame:
    required = {"actual", "pred"}
    missing = required - set(predictions.columns)
    if missing:
        raise ValueError(f"预测结果缺少列: {sorted(missing)}")
    df = predictions.copy()
    df["err"] = df["pred"] - df["actual"]
    df["abs_err"] = df["err"].abs()
    df["sq_err"] = df["err"] ** 2
    if "scale" in df.columns:
        df["scaled_sq_err"] = df["sq_err"] / df["scale"].clip(lower=1e-9)
    else:
        df["scaled_sq_err"] = np.nan
    return df


def evaluate_predictions(
    predictions: pd.DataFrame,
    group_cols: Iterable[str] = ("model",),
) -> pd.DataFrame:
    """Aggregate error metrics over raw prediction rows.

    WMAPE/bias are demand-weighted; MAE/RMSE/RMSSE are means over rows or series.
    """
    df = add_error_columns(predictions)
    group_cols = list(group_cols)
    if not group_cols:
        raise ValueError("group_cols 不能为空")

    grouped = df.groupby(group_cols, dropna=False)
    summary = grouped.agg(
        n=("actual", "size"),
        actual_sum=("actual", "sum"),
        abs_err_sum=("abs_err", "sum"),
        err_sum=("err", "sum"),
        mae=("abs_err", "mean"),
        rmse=("sq_err", lambda values: float(np.sqrt(values.mean()))),
        rmsse=(
            "scaled_sq_err",
            lambda values: float(np.sqrt(values.mean())) if values.notna().any() else np.nan,
        ),
    ).reset_index()

    denominator = summary["actual_sum"].replace(0, np.nan)
    summary["wmape"] = summary["abs_err_sum"] / denominator
    summary["bias"] = summary["err_sum"] / denominator
    summary.loc[summary["actual_sum"] == 0, ["wmape", "bias"]] = 0.0
    return summary


def summarize(
    predictions: pd.DataFrame,
    group_cols: Sequence[str] = ("model",),
) -> dict[str, pd.DataFrame]:
    """Return overall, horizon-bucket, and fold-level summaries."""
    df = predictions.copy()
    if "horizon" in df.columns:
        df["horizon_bucket"] = df["horizon"].map(horizon_bucket)

    result: dict[str, pd.DataFrame] = {
        "overall": evaluate_predictions(df, group_cols),
    }
    if "horizon_bucket" in df.columns:
        result["by_horizon"] = evaluate_predictions(df, [*group_cols, "horizon_bucket"])
    if "fold" in df.columns:
        result["by_fold"] = evaluate_predictions(df, [*group_cols, "fold"])
    return result


def format_metric_table(df: pd.DataFrame) -> pd.DataFrame:
    formatted = df.copy()
    for col in ("wmape", "bias"):
        if col in formatted.columns:
            formatted[col] = formatted[col].map(
                lambda value: "—" if pd.isna(value) else f"{value:.2%}"
            )
    for col in ("mae", "rmse", "rmsse"):
        if col in formatted.columns:
            formatted[col] = formatted[col].map(
                lambda value: "—" if pd.isna(value) else f"{value:.2f}"
            )
    return formatted
