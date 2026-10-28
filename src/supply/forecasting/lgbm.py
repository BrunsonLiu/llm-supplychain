"""Global LightGBM demand model with early stopping."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "tweedie",
    "tweedie_variance_power": 1.3,
    "metric": "mae",
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 40,
    "feature_fraction": 0.85,
    "bagging_fraction": 0.85,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": 42,
}


def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_valid: Optional[pd.DataFrame] = None,
    y_valid: Optional[pd.Series] = None,
    params: Optional[dict[str, Any]] = None,
    num_boost_round: int = 1000,
    early_stopping_rounds: int = 50,
):
    import lightgbm as lgb

    merged_params = {**DEFAULT_PARAMS, **(params or {})}
    train_data = lgb.Dataset(X_train, label=y_train, free_raw_data=False)
    callbacks = [lgb.log_evaluation(0)]
    valid_sets = []

    if X_valid is not None and y_valid is not None and len(X_valid) > 0:
        valid_sets = [lgb.Dataset(X_valid, label=y_valid, reference=train_data)]
        callbacks.append(lgb.early_stopping(early_stopping_rounds, verbose=False))

    model = lgb.train(
        merged_params,
        train_data,
        num_boost_round=num_boost_round,
        valid_sets=valid_sets,
        callbacks=callbacks,
    )
    return model


def predict_model(model, X: pd.DataFrame) -> np.ndarray:
    predictions = np.asarray(model.predict(X), dtype=float)
    predictions[~np.isfinite(predictions)] = 0.0
    return np.maximum(predictions, 0.0)


def feature_importance(model, top_n: int = 20) -> pd.DataFrame:
    names = model.feature_name()
    gains = model.feature_importance(importance_type="gain")
    frame = pd.DataFrame({"feature": names, "gain": gains})
    return frame.sort_values("gain", ascending=False).head(top_n).reset_index(drop=True)
