"""Classical demand forecasting baselines with a uniform interface."""
from __future__ import annotations

import warnings
from typing import Callable, Dict

import numpy as np

ForecastFn = Callable[[np.ndarray, int, int], np.ndarray]


def _as_float(history) -> np.ndarray:
    values = np.asarray(history, dtype=float)
    return values[np.isfinite(values)]


def _clip(pred: np.ndarray, horizon: int) -> np.ndarray:
    values = np.asarray(pred, dtype=float).reshape(-1)
    if values.size < horizon:
        values = np.pad(values, (0, horizon - values.size), mode="edge")
    values = values[:horizon]
    values[~np.isfinite(values)] = 0.0
    return np.maximum(values, 0.0)


def naive(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    values = _as_float(history)
    level = values[-1] if values.size else 0.0
    return _clip(np.full(horizon, level), horizon)


def seasonal_naive(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    values = _as_float(history)
    if values.size == 0:
        return np.zeros(horizon)
    if values.size < seasonality:
        return naive(values, horizon, seasonality)
    predictions = []
    for step in range(1, horizon + 1):
        index = values.size - seasonality + step - 1
        predictions.append(values[index] if index >= 0 else values[-1])
    return _clip(np.asarray(predictions), horizon)


def moving_average(history, horizon: int, window: int = 4, seasonality: int = 52) -> np.ndarray:
    values = _as_float(history)
    if values.size == 0:
        return np.zeros(horizon)
    window = max(1, min(window, values.size))
    level = float(np.mean(values[-window:]))
    return _clip(np.full(horizon, level), horizon)


def croston_sba(history, horizon: int, seasonality: int = 52, alpha: float = 0.1) -> np.ndarray:
    """Croston with the Syntetos-Boylan approximation for intermittent demand."""
    values = _as_float(history)
    positive = np.flatnonzero(values > 0)
    if positive.size == 0:
        return np.zeros(horizon)

    level = float(values[positive[0]])
    interval = 1.0
    last_positive = int(positive[0])
    for index in range(last_positive + 1, values.size):
        demand = values[index]
        if demand <= 0:
            continue
        gap = float(index - last_positive)
        level = alpha * demand + (1 - alpha) * level
        interval = alpha * gap + (1 - alpha) * interval
        last_positive = index

    rate = level / max(interval, 1e-9) * (1 - alpha / 2)
    return _clip(np.full(horizon, rate), horizon)


def holt(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    values = _as_float(history)
    if values.size < 3:
        return moving_average(values, horizon, window=2, seasonality=seasonality)
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                values,
                trend="add",
                seasonal=None,
                initialization_method="estimated",
            )
            fitted = model.fit(optimized=True)
            predictions = np.asarray(fitted.forecast(horizon), dtype=float)
        return _clip(predictions, horizon)
    except Exception:  # noqa: BLE001 - numerical failures fall back to the mean
        return moving_average(values, horizon, window=4, seasonality=seasonality)


def holt_winters(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    """Additive Holt-Winters; falls back to Holt below two full seasonal cycles."""
    values = _as_float(history)
    if values.size < 2 * seasonality:
        return holt(values, horizon, seasonality)
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = ExponentialSmoothing(
                values,
                trend="add",
                seasonal="add",
                seasonal_periods=seasonality,
                initialization_method="estimated",
            )
            fitted = model.fit(optimized=True)
            predictions = np.asarray(fitted.forecast(horizon), dtype=float)
        return _clip(predictions, horizon)
    except Exception:  # noqa: BLE001 - fall back rather than drop the model
        return holt(values, horizon, seasonality)


def _ma4(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    return moving_average(history, horizon, window=4, seasonality=seasonality)


def _ma8(history, horizon: int, seasonality: int = 52) -> np.ndarray:
    return moving_average(history, horizon, window=8, seasonality=seasonality)


BASELINES: Dict[str, ForecastFn] = {
    "naive": naive,
    "seasonal_naive": seasonal_naive,
    "ma4": _ma4,
    "ma8": _ma8,
    "croston_sba": croston_sba,
    "holt": holt,
    "holt_winters": holt_winters,
}

BASELINE_LABELS: Dict[str, str] = {
    "naive": "Naive",
    "seasonal_naive": "Seasonal Naive",
    "ma4": "MA(4)",
    "ma8": "MA(8)",
    "croston_sba": "Croston-SBA",
    "holt": "Holt",
    "holt_winters": "Holt-Winters",
    "lightgbm": "LightGBM (global)",
}
