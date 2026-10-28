"""Feature engineering for a global multi-SKU demand model.

Leakage controls:
- lag/rolling features are shifted by one week;
- SKU summaries use an expanding window capped at the first 52 weeks;
- calendar features for the target week are deterministic and known in advance.
"""
from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np
import pandas as pd

LAGS = (1, 2, 3, 4, 8, 13, 26, 52)
ROLLING_WINDOWS = (4, 8, 13, 26, 52)
SEASONAL_ANCHORS = (51, 52, 53)
META_COLUMNS = {
    "sku",
    "week",
    "demand",
    "revenue",
    "orders",
    "description",
    "country",
    "avg_price",
    "target",
    "target_week",
}


def calendar_features(weeks: pd.Series) -> pd.DataFrame:
    """Annual retail calendar features. ``weeks`` must be datetime-like."""
    weeks = pd.to_datetime(pd.Series(weeks))
    iso_week = weeks.dt.isocalendar().week.astype(int).clip(upper=52)
    month = weeks.dt.month.astype(int)
    output = pd.DataFrame(index=weeks.index)
    output["week_of_year"] = iso_week
    output["month"] = month
    output["sin_woy"] = np.sin(2 * np.pi * iso_week / 52.0)
    output["cos_woy"] = np.cos(2 * np.pi * iso_week / 52.0)
    output["sin_month"] = np.sin(2 * np.pi * month / 12.0)
    output["cos_month"] = np.cos(2 * np.pi * month / 12.0)
    output["is_q4"] = month.isin([10, 11, 12]).astype(int)
    # Signed distance to the Christmas peak (week 52), wrapped to [-26, 25].
    output["weeks_to_christmas"] = ((52 - iso_week + 26) % 52) - 26
    return output


def _sku_summary_features(df: pd.DataFrame, cap: int = 52) -> pd.DataFrame:
    """Expanding mean/std/non-zero rate, capped at the first ``cap`` weeks."""
    grouped = df.groupby("sku", sort=False)
    df["_cum_sum"] = grouped["demand"].cumsum()
    df["_cum_sq"] = grouped["demand"].transform(lambda values: (values**2).cumsum())
    df["_cum_count"] = grouped.cumcount() + 1
    df["_cum_nonzero"] = grouped["demand"].transform(lambda values: (values > 0).cumsum())

    first = (
        df[df["t"] < cap]
        .groupby("sku", as_index=False)
        .agg(
            _first_sum=("demand", "sum"),
            _first_sq=("demand", lambda values: float((values**2).sum())),
            _first_nonzero=("demand", lambda values: int((values > 0).sum())),
            _first_n=("demand", "size"),
        )
    )
    df = df.merge(first, on="sku", how="left")

    capped = df["t"] >= cap
    df["sku_mean"] = np.where(
        capped,
        df["_first_sum"] / df["_first_n"].replace(0, np.nan),
        df["_cum_sum"] / df["_cum_count"],
    )
    sq_mean = np.where(
        capped,
        df["_first_sq"] / df["_first_n"].replace(0, np.nan),
        df["_cum_sq"] / df["_cum_count"],
    )
    df["sku_std"] = np.sqrt(np.maximum(sq_mean - df["sku_mean"] ** 2, 0.0))
    df["sku_cv"] = df["sku_std"] / df["sku_mean"].replace(0, np.nan)
    df["sku_nonzero_rate"] = np.where(
        capped,
        df["_first_nonzero"] / df["_first_n"].replace(0, np.nan),
        df["_cum_nonzero"] / df["_cum_count"],
    )
    df["sku_mean"] = df["sku_mean"].fillna(0.0)
    df["sku_std"] = df["sku_std"].fillna(0.0)
    df["sku_cv"] = df["sku_cv"].fillna(0.0)
    df["sku_nonzero_rate"] = df["sku_nonzero_rate"].fillna(0.0)
    return df.drop(columns=["_cum_sum", "_cum_sq", "_cum_count", "_cum_nonzero",
                            "_first_sum", "_first_sq", "_first_nonzero", "_first_n"])


def origin_features(panel: pd.DataFrame, cutoff: pd.Timestamp, seasonality: int = 52) -> pd.DataFrame:
    """Features known at each origin week ``t`` (forecasting t+1 ... t+H)."""
    cutoff = pd.Timestamp(cutoff)
    df = panel[panel["week"] <= cutoff].sort_values(["sku", "week"]).reset_index(drop=True)
    if df.empty:
        raise ValueError(f"截止 {cutoff.date()} 没有历史数据")
    df["t"] = df.groupby("sku", sort=False).cumcount()

    grouped = df.groupby("sku", sort=False)
    for lag in LAGS:
        df[f"lag_{lag}"] = grouped["demand"].shift(lag)

    shifted = grouped["demand"].shift(1)
    for window in ROLLING_WINDOWS:
        min_periods = max(2, window // 2)
        rolling = shifted.groupby(df["sku"]).transform(
            lambda values, w=window, m=min_periods: values.rolling(w, min_periods=m).mean()
        )
        df[f"roll_mean_{window}"] = rolling
        rolling_std = shifted.groupby(df["sku"]).transform(
            lambda values, w=window, m=min_periods: values.rolling(w, min_periods=m).std()
        )
        df[f"roll_std_{window}"] = rolling_std
        rolling_max = shifted.groupby(df["sku"]).transform(
            lambda values, w=window, m=min_periods: values.rolling(w, min_periods=m).max()
        )
        df[f"roll_max_{window}"] = rolling_max

    is_zero = (df["demand"] == 0).astype(int)
    run_id = (is_zero == 0).cumsum()
    df["zero_streak"] = is_zero.groupby([df["sku"], run_id]).cumsum().astype(float)

    df = _sku_summary_features(df, cap=seasonality)

    if "avg_price" in df.columns:
        df["price"] = pd.to_numeric(df["avg_price"], errors="coerce").fillna(0.0)
        df["price_change_4"] = (
            df.groupby("sku", sort=False)["price"].pct_change(4, fill_method=None)
        ).replace([np.inf, -np.inf], np.nan)
        df["price_lag_4"] = df.groupby("sku", sort=False)["price"].shift(4)
    else:
        df["price"] = 0.0
        df["price_change_4"] = 0.0
        df["price_lag_4"] = 0.0

    origin_calendar = calendar_features(df["week"]).add_prefix("origin_")
    df = pd.concat([df, origin_calendar], axis=1)

    # Drop non-feature columns only after target construction; keep them here.
    return df


def target_calendar(weeks: pd.Series, prefix: str = "target_") -> pd.DataFrame:
    return calendar_features(weeks).add_prefix(prefix)


def _attach_seasonal_anchors(frame: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """Demand in the same calendar week one year before the target week.

    ``history`` must end at the forecast origin, so every anchor is observable
    at the origin for horizons up to ``min(SEASONAL_ANCHORS)`` weeks. This gives
    the model the same seasonal-naive anchor that classical baselines use.
    """
    lookup = history.set_index(["sku", "week"])["demand"]
    for lag in SEASONAL_ANCHORS:
        anchor_week = frame["target_week"] - pd.Timedelta(weeks=lag)
        keys = pd.MultiIndex.from_arrays([frame["sku"], anchor_week])
        frame[f"seasonal_lag_{lag}"] = lookup.reindex(keys).to_numpy(dtype=float)
    return frame


def feature_columns(frame: pd.DataFrame) -> list[str]:
    return [col for col in frame.columns if col not in META_COLUMNS]


def build_training_frame(
    panel: pd.DataFrame,
    cutoff: pd.Timestamp,
    horizon: int,
    seasonality: int = 52,
) -> Tuple[pd.DataFrame, pd.Series, pd.DataFrame, list[str]]:
    """Build a direct multi-horizon training set ending at ``cutoff``."""
    cutoff = pd.Timestamp(cutoff)
    base = (
        panel[panel["week"] <= cutoff]
        .sort_values(["sku", "week"])
        .reset_index(drop=True)
    )
    features = origin_features(base, cutoff, seasonality=seasonality)
    if len(features) != len(base):
        raise RuntimeError("特征行数与面板行数不一致")

    chunks = []
    for step in range(1, horizon + 1):
        target = base.groupby("sku", sort=False)["demand"].shift(-step)
        target_week = base["week"] + pd.Timedelta(weeks=step)
        mask = target.notna() & (target_week <= cutoff)
        if not mask.any():
            continue
        chunk = features.loc[mask].copy()
        chunk["horizon"] = step
        chunk["target_week"] = target_week[mask]
        chunk["target"] = target[mask]
        chunk = _attach_seasonal_anchors(chunk, base)
        chunk = pd.concat(
            [chunk, target_calendar(chunk["target_week"])],
            axis=1,
        )
        chunks.append(chunk)

    if not chunks:
        raise ValueError(f"截止 {cutoff.date()} 无法构造训练样本（horizon={horizon}）")

    train = pd.concat(chunks, ignore_index=True)
    train = train[train["target"] >= 0].copy()
    target = train.pop("target").astype(float)
    meta = train[["sku", "week", "target_week", "horizon"]].copy()
    columns = feature_columns(train)
    # A feature that is entirely missing in training but present at prediction
    # sends trees down untrained branches, so keep only anchors with coverage.
    columns = [
        col
        for col in columns
        if not col.startswith("seasonal_lag_") or train[col].notna().any()
    ]
    return train[columns], target, meta, columns


def build_prediction_frame(
    panel: pd.DataFrame,
    cutoff: pd.Timestamp,
    horizon: int,
    feature_names: Iterable[str] | None = None,
    seasonality: int = 52,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Features for the single origin ``cutoff``, one row per SKU and horizon."""
    cutoff = pd.Timestamp(cutoff)
    features = origin_features(panel, cutoff, seasonality=seasonality)
    origin = features[features["week"] == cutoff].copy()
    if origin.empty:
        raise ValueError(f"截止 {cutoff.date()} 没有可用于预测的 SKU")

    chunks = []
    for step in range(1, horizon + 1):
        chunk = origin.copy()
        chunk["horizon"] = step
        chunk["target_week"] = cutoff + pd.Timedelta(weeks=step)
        chunk = _attach_seasonal_anchors(chunk, features)
        chunk = pd.concat(
            [chunk, target_calendar(chunk["target_week"])],
            axis=1,
        )
        chunks.append(chunk)

    prediction = pd.concat(chunks, ignore_index=True)
    meta = prediction[["sku", "week", "target_week", "horizon"]].copy()
    columns = list(feature_names) if feature_names is not None else feature_columns(prediction)
    return prediction.reindex(columns=columns), meta
