"""Rolling-origin backtesting for classical and global ML forecasters."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .baselines import BASELINES
from .features import build_prediction_frame, build_training_frame
from .lgbm import predict_model, train_model
from .metrics import rmsse_scale

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    horizon: int = 13
    n_folds: int = 4
    min_train_weeks: int = 52
    seasonality: int = 52
    min_train_nonzero_weeks: int = 13
    models: Sequence[str] = (
        "naive",
        "seasonal_naive",
        "ma4",
        "ma8",
        "croston_sba",
        "holt",
    )
    include_lgbm: bool = True
    lgbm_params: Optional[Dict[str, Any]] = None
    lgbm_num_boost_round: int = 1000
    lgbm_early_stopping: int = 50

    def validate(self) -> None:
        if self.horizon <= 0 or self.n_folds <= 0:
            raise ValueError("horizon 和 n_folds 必须为正整数")
        unknown = set(self.models) - set(BASELINES)
        if unknown:
            raise ValueError(f"未知基线模型: {sorted(unknown)}")


@dataclass
class Fold:
    index: int
    cutoff: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_weeks: int
    test_weeks: int


@dataclass
class BacktestResult:
    predictions: pd.DataFrame
    timings: pd.DataFrame
    folds: List[Fold]
    feature_importance: Dict[int, pd.DataFrame] = field(default_factory=dict)
    config: BacktestConfig = field(default_factory=BacktestConfig)


def make_folds(panel: pd.DataFrame, config: BacktestConfig) -> List[Fold]:
    weeks = pd.Index(sorted(pd.to_datetime(panel["week"].unique())))
    if len(weeks) < 2:
        raise ValueError("面板至少需要两周数据")
    gaps = np.diff(weeks.values).astype("timedelta64[D]").astype(int)
    if not np.all(gaps == 7):
        raise ValueError("面板周序列不连续，请先补齐缺失周")

    required = config.min_train_weeks + config.n_folds * config.horizon
    if len(weeks) < required:
        raise ValueError(
            f"数据不足：需要至少 {required} 周，当前 {len(weeks)} 周。"
            "可减少 folds/horizon 或降低 min_train_weeks。"
        )

    folds: List[Fold] = []
    for index in range(config.n_folds):
        test_end_pos = len(weeks) - 1 - (config.n_folds - 1 - index) * config.horizon
        test_start_pos = test_end_pos - config.horizon + 1
        cutoff_pos = test_start_pos - 1
        folds.append(
            Fold(
                index=index,
                cutoff=pd.Timestamp(weeks[cutoff_pos]),
                test_start=pd.Timestamp(weeks[test_start_pos]),
                test_end=pd.Timestamp(weeks[test_end_pos]),
                train_weeks=cutoff_pos + 1,
                test_weeks=config.horizon,
            )
        )
    return folds


def _validate_panel(panel: pd.DataFrame) -> pd.DataFrame:
    required = {"sku", "week", "demand"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"面板缺少列: {sorted(missing)}")
    df = panel.copy()
    df["week"] = pd.to_datetime(df["week"])
    if df.duplicated(["sku", "week"]).any():
        raise ValueError("面板存在重复的 (sku, week)")
    counts = df.groupby("sku")["week"].nunique()
    if counts.nunique() != 1:
        raise ValueError("不同 SKU 的周数不一致，请先补全面板")
    return df.sort_values(["sku", "week"]).reset_index(drop=True)


def run_backtest(
    panel: pd.DataFrame,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    config = config or BacktestConfig()
    config.validate()
    panel = _validate_panel(panel)
    folds = make_folds(panel, config)

    all_predictions: List[pd.DataFrame] = []
    timing_rows: List[Dict[str, Any]] = []
    importances: Dict[int, pd.DataFrame] = {}

    for fold in folds:
        train = panel[panel["week"] <= fold.cutoff]
        test = panel[
            (panel["week"] > fold.cutoff) & (panel["week"] <= fold.test_end)
        ]
        train_matrix = train.pivot(index="week", columns="sku", values="demand").sort_index()
        test_matrix = test.pivot(index="week", columns="sku", values="demand").sort_index()
        # A SKU with no meaningful training history cannot be forecast by any
        # of these models; it belongs to a launch/new-product process instead.
        nonzero_weeks = (train_matrix > 0).sum()
        skus = train_matrix.columns[
            nonzero_weeks >= config.min_train_nonzero_weeks
        ].to_numpy()
        if len(skus) == 0:
            raise RuntimeError(f"折 {fold.index} 没有满足最小历史非零周数的 SKU")
        train_matrix = train_matrix[skus]
        actual_matrix = test_matrix.reindex(index=pd.Index(sorted(test["week"].unique())), columns=skus)

        if actual_matrix.shape[0] != config.horizon:
            raise RuntimeError(
                f"折 {fold.index} 测试周数 {actual_matrix.shape[0]} != horizon {config.horizon}"
            )

        scales = np.array(
            [
                rmsse_scale(train_matrix[sku].to_numpy(dtype=float), config.seasonality)
                for sku in skus
            ],
            dtype=float,
        )

        for model_name in config.models:
            started = time.perf_counter()
            forecast_fn = BASELINES[model_name]
            predictions = np.zeros((config.horizon, len(skus)), dtype=float)
            for column, sku in enumerate(skus):
                history = train_matrix[sku].to_numpy(dtype=float)
                predictions[:, column] = forecast_fn(history, config.horizon, config.seasonality)
            all_predictions.append(
                _prediction_frame(
                    predictions=predictions,
                    actual=actual_matrix.to_numpy(dtype=float),
                    weeks=actual_matrix.index,
                    skus=skus,
                    model=model_name,
                    fold=fold,
                    scales=scales,
                )
            )
            timing_rows.append(
                {
                    "model": model_name,
                    "fold": fold.index,
                    "seconds": time.perf_counter() - started,
                }
            )

        if config.include_lgbm:
            started = time.perf_counter()
            try:
                prediction, importance = _run_lgbm_fold(panel, train_matrix, fold, config, scales)
                prediction = prediction[prediction["sku"].isin(skus)].reset_index(drop=True)
                all_predictions.append(prediction)
                importances[fold.index] = importance
            except Exception as exc:  # noqa: BLE001 - keep other models reportable
                logger.exception("LightGBM 折 %d 失败: %s", fold.index, exc)
            timing_rows.append(
                {
                    "model": "lightgbm",
                    "fold": fold.index,
                    "seconds": time.perf_counter() - started,
                }
            )

    if not all_predictions:
        raise RuntimeError("没有产生任何预测结果")

    predictions = pd.concat(all_predictions, ignore_index=True)
    predictions = predictions[predictions["actual"].notna()].reset_index(drop=True)
    return BacktestResult(
        predictions=predictions,
        timings=pd.DataFrame(timing_rows),
        folds=folds,
        feature_importance=importances,
        config=config,
    )


def _prediction_frame(
    predictions: np.ndarray,
    actual: np.ndarray,
    weeks: Iterable[pd.Timestamp],
    skus: Iterable[str],
    model: str,
    fold: Fold,
    scales: np.ndarray,
) -> pd.DataFrame:
    frames = []
    skus = list(skus)
    weeks = list(weeks)
    for step in range(predictions.shape[0]):
        frames.append(
            pd.DataFrame(
                {
                    "model": model,
                    "fold": fold.index,
                    "cutoff": fold.cutoff,
                    "sku": skus,
                    "horizon": step + 1,
                    "week": weeks[step],
                    "actual": actual[step],
                    "pred": predictions[step],
                    "scale": scales,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _run_lgbm_fold(
    panel: pd.DataFrame,
    train_matrix: pd.DataFrame,
    fold: Fold,
    config: BacktestConfig,
    scales: np.ndarray,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    inner_cutoff = fold.cutoff - pd.Timedelta(weeks=config.horizon)
    use_validation = inner_cutoff >= train_matrix.index.min()

    best_iteration = 200
    if use_validation:
        X_inner, y_inner, _, columns = build_training_frame(
            panel, inner_cutoff, config.horizon, seasonality=config.seasonality
        )
        X_valid, meta_valid = build_prediction_frame(
            panel,
            inner_cutoff,
            config.horizon,
            feature_names=columns,
            seasonality=config.seasonality,
        )
        actual_map = panel.set_index(["sku", "week"])["demand"]
        valid_actual = pd.Series(
            [
                actual_map.get((sku, target_week), np.nan)
                for sku, target_week in zip(meta_valid["sku"], meta_valid["target_week"])
            ],
            index=meta_valid.index,
        )
        valid_mask = valid_actual.notna()
        if valid_mask.any():
            model = train_model(
                X_inner,
                y_inner,
                X_valid.loc[valid_mask],
                valid_actual.loc[valid_mask],
                params=config.lgbm_params,
                num_boost_round=config.lgbm_num_boost_round,
                early_stopping_rounds=config.lgbm_early_stopping,
            )
            best_iteration = int(getattr(model, "best_iteration", 0) or 200)
        else:
            model = train_model(
                X_inner,
                y_inner,
                params=config.lgbm_params,
                num_boost_round=200,
            )
            best_iteration = 200
    else:
        columns = None

    X_train, y_train, _, columns = build_training_frame(
        panel, fold.cutoff, config.horizon, seasonality=config.seasonality
    )
    final_model = train_model(
        X_train,
        y_train,
        params=config.lgbm_params,
        num_boost_round=max(best_iteration, 50),
    )
    X_prediction, meta_prediction = build_prediction_frame(
        panel,
        fold.cutoff,
        config.horizon,
        feature_names=columns,
        seasonality=config.seasonality,
    )
    predicted = predict_model(final_model, X_prediction)

    actual_map = panel.set_index(["sku", "week"])["demand"]
    prediction = meta_prediction.copy()
    prediction["actual"] = [
        actual_map.get((sku, target_week), np.nan)
        for sku, target_week in zip(prediction["sku"], prediction["target_week"])
    ]
    prediction = prediction[prediction["actual"].notna()].copy()
    prediction["pred"] = predicted[prediction.index.to_numpy()]
    prediction["model"] = "lightgbm"
    prediction["fold"] = fold.index
    prediction["cutoff"] = fold.cutoff
    prediction = prediction.drop(columns=["week"]).rename(columns={"target_week": "week"})
    prediction["scale"] = prediction["sku"].map(dict(zip(train_matrix.columns, scales)))
    prediction = prediction[
        ["model", "fold", "cutoff", "sku", "horizon", "week", "actual", "pred", "scale"]
    ].reset_index(drop=True)

    importance = _importance_frame(final_model)
    return prediction, importance


def _importance_frame(model) -> pd.DataFrame:
    names = model.feature_name()
    gains = model.feature_importance(importance_type="gain")
    return (
        pd.DataFrame({"feature": names, "gain": gains})
        .sort_values("gain", ascending=False)
        .head(20)
        .reset_index(drop=True)
    )
