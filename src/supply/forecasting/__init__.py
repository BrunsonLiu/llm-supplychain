"""滚动回测与需求预测：指标、基线、特征、LightGBM、回测编排。"""
from .backtest import BacktestConfig, BacktestResult, Fold, make_folds, run_backtest
from .baselines import BASELINES, BASELINE_LABELS
from .features import build_prediction_frame, build_training_frame, calendar_features
from .lgbm import DEFAULT_PARAMS, feature_importance, predict_model, train_model
from .metrics import (
    add_error_columns,
    bias,
    evaluate_predictions,
    format_metric_table,
    horizon_bucket,
    mae,
    rmse,
    rmsse_scale,
    summarize,
    wmape,
)
from .report import aggregate_view, build_report, write_report

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "Fold",
    "make_folds",
    "run_backtest",
    "BASELINES",
    "BASELINE_LABELS",
    "build_prediction_frame",
    "build_training_frame",
    "calendar_features",
    "DEFAULT_PARAMS",
    "feature_importance",
    "predict_model",
    "train_model",
    "add_error_columns",
    "bias",
    "evaluate_predictions",
    "format_metric_table",
    "horizon_bucket",
    "mae",
    "rmse",
    "rmsse_scale",
    "summarize",
    "wmape",
    "build_report",
    "write_report",
    "aggregate_view",
]
