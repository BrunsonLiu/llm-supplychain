# -*- coding: utf-8 -*-
"""Week-1 tests: ETL, metrics, baselines, features, backtest, report.

Run: python tests/test_forecasting.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from supply.data.online_retail import (
    aggregate_weekly,
    clean_transactions,
    select_skus,
)
from supply.forecasting import (
    BASELINES,
    BacktestConfig,
    build_prediction_frame,
    build_training_frame,
    evaluate_predictions,
    make_folds,
    run_backtest,
    summarize,
    write_report,
)
from supply.forecasting.metrics import bias, mae, rmse, rmsse_scale, wmape


def _synthetic_panel(n_skus: int = 8, n_weeks: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    weeks = pd.date_range("2020-01-06", periods=n_weeks, freq="7D")
    rows = []
    for index in range(n_skus):
        sku = f"SKU{index:03d}"
        base = 5 + index * 3
        for position, week in enumerate(weeks):
            seasonal = 1.0 + 0.25 * np.sin(2 * np.pi * position / 26)
            demand = max(0.0, rng.poisson(base * seasonal))
            if rng.random() < 0.12:
                demand = 0.0
            rows.append(
                {
                    "sku": sku,
                    "week": week,
                    "demand": float(demand),
                    "revenue": float(demand * (2.0 + index * 0.1)),
                    "orders": int(demand > 0),
                    "description": f"item {index}",
                    "country": "United Kingdom",
                    "avg_price": 2.0 + index * 0.1,
                }
            )
    return pd.DataFrame(rows)


def test_etl_cleaning_and_aggregation():
    raw = pd.DataFrame(
        {
            "invoice": ["1001", "1001", "1002", "C1003", "POST", "1004", "1005"],
            "stock_code": ["10001", "10001", "10002", "10003", "POST", "10004", "10005"],
            "description": ["a", "a", "b", "c", "postage", "d", "e"],
            "quantity": [3, 3, 5, 2, 1, -2, 4],
            "invoice_date": pd.to_datetime(
                [
                    "2020-01-06 10:00",
                    "2020-01-06 10:00",
                    "2020-01-07 11:00",
                    "2020-01-08 12:00",
                    "2020-01-08 12:00",
                    "2020-01-09 13:00",
                    "2020-01-13 09:00",
                ]
            ),
            "price": [2.0, 2.0, 1.5, 3.0, 0.0, 1.0, 2.5],
            "customer_id": [1, 1, 2, 3, 4, 5, 6],
            "country": ["UK"] * 7,
        }
    )
    clean, stats = clean_transactions(raw)

    assert stats["raw_rows"] == 7
    assert stats["dropped_duplicates"] == 1, stats
    assert stats["dropped_cancelled"] == 1
    assert stats["dropped_non_product"] == 1
    assert stats["dropped_non_positive"] == 1
    assert stats["clean_rows"] == 3, clean
    assert set(clean["sku"]) == {"10001", "10002", "10005"}
    assert clean["week"].dt.weekday.eq(0).all()

    # A non-zero-demand SKU that is absent in a later week must be filled with zero.
    panel = aggregate_weekly(clean)
    assert panel.groupby("sku")["week"].nunique().nunique() == 1
    assert (panel["demand"] >= 0).all()
    assert len(panel) == panel["sku"].nunique() * panel["week"].nunique()

    selected, sku_stats = select_skus(panel, top_n=2, min_nonzero_weeks=1)
    assert selected["sku"].nunique() <= 2
    assert not sku_stats.empty
    print("[OK] ETL 去重/清洗/补零/筛选")


def test_metrics_known_values():
    actual = [10.0, 20.0]
    pred = [12.0, 18.0]
    assert abs(wmape(actual, pred) - 4 / 30) < 1e-12
    assert abs(bias(actual, pred)) < 1e-12
    assert mae(actual, pred) == 2.0
    assert rmse(actual, pred) == 2.0
    assert rmsse_scale(np.zeros(10), seasonality=4) >= 1.0

    frame = pd.DataFrame(
        {
            "model": ["a", "a", "b", "b"],
            "actual": [10.0, 20.0, 10.0, 20.0],
            "pred": [12.0, 18.0, 0.0, 0.0],
            "scale": [4.0, 4.0, 4.0, 4.0],
            "horizon": [1, 2, 1, 2],
        }
    )
    summary = summarize(frame)
    overall = summary["overall"].set_index("model")
    assert abs(overall.loc["a", "wmape"] - 4 / 30) < 1e-12
    assert abs(overall.loc["b", "wmape"] - 1.0) < 1e-12
    assert "by_horizon" in summary and "by_fold" not in summary
    print("[OK] 指标计算与分组汇总")


def test_baselines_output_shape():
    history = 50 + 10 * np.sin(np.arange(80) * 2 * np.pi / 26)
    for name, fn in BASELINES.items():
        forecast = np.asarray(fn(history, 6, 52), dtype=float)
        assert forecast.shape == (6,), f"{name} shape {forecast.shape}"
        assert np.isfinite(forecast).all(), f"{name} 出现非有限值"
        assert (forecast >= 0).all(), f"{name} 出现负预测"
    print("[OK] 基线模型输出形状与取值")


def test_features_no_future_leakage():
    panel = _synthetic_panel(n_weeks=120)
    cutoff = panel["week"].max() - pd.Timedelta(weeks=8)
    X, y, meta, columns = build_training_frame(panel, cutoff, horizon=4)
    assert len(X) == len(y) == len(meta)
    assert (meta["target_week"] <= cutoff).all()
    assert (y >= 0).all()
    assert "lag_1" in columns and "roll_mean_4" in columns

    features = build_prediction_frame(panel, cutoff, horizon=4, feature_names=columns)
    X_pred, meta_pred = features
    assert len(X_pred) == panel["sku"].nunique() * 4
    assert (meta_pred["target_week"] > cutoff).all()
    assert list(X_pred.columns) == list(columns)

    # lag_1 at the latest training origin equals the previous week's demand.
    sku = panel["sku"].iloc[0]
    sku_panel = panel[panel["sku"] == sku].sort_values("week").set_index("week")
    latest_origin = meta.loc[meta["sku"] == sku, "week"].max()
    origin_row = meta[(meta["sku"] == sku) & (meta["week"] == latest_origin)].index[0]
    assert latest_origin <= cutoff
    assert X.loc[origin_row, "lag_1"] == sku_panel["demand"].shift(1).loc[latest_origin]

    # The seasonal anchor is the same calendar week one year before the target.
    anchor_week = meta_pred["target_week"].iloc[0] - pd.Timedelta(weeks=52)
    assert anchor_week >= sku_panel.index.min()
    assert X_pred.loc[0, "seasonal_lag_52"] == sku_panel.loc[anchor_week, "demand"]
    print("[OK] 特征构造与防泄漏约束")


def test_folds_and_backtest():
    panel = _synthetic_panel(n_weeks=60)
    config = BacktestConfig(
        horizon=4,
        n_folds=2,
        min_train_weeks=40,
        seasonality=13,
        models=("naive", "seasonal_naive", "ma4", "croston_sba"),
        include_lgbm=False,
    )
    folds = make_folds(panel, config)
    assert [fold.index for fold in folds] == [0, 1]
    assert folds[0].cutoff < folds[0].test_start <= folds[0].test_end
    assert folds[0].test_end <= folds[1].cutoff < folds[1].test_start

    result = run_backtest(panel, config)
    predictions = result.predictions
    assert set(predictions["model"]) == set(config.models)
    assert predictions["actual"].notna().all()
    assert (predictions["pred"] >= 0).all()
    assert set(predictions["fold"]) == {0, 1}
    assert len(predictions) == len(config.models) * 2 * 4 * panel["sku"].nunique()

    metrics = evaluate_predictions(predictions)
    assert set(metrics["model"]) == set(config.models)
    print("[OK] 滚动折与基线回测")

    lgbm_config = BacktestConfig(
        horizon=4,
        n_folds=2,
        min_train_weeks=40,
        seasonality=13,
        models=("naive",),
        include_lgbm=True,
        lgbm_num_boost_round=60,
        lgbm_early_stopping=10,
    )
    lgbm_result = run_backtest(panel, lgbm_config)
    assert "lightgbm" in set(lgbm_result.predictions["model"])
    lgbm_rows = lgbm_result.predictions[lgbm_result.predictions["model"] == "lightgbm"]
    assert lgbm_rows["actual"].notna().all()
    assert (lgbm_rows["pred"] >= 0).all()
    assert lgbm_result.feature_importance, "LightGBM 特征重要性为空"
    print("[OK] LightGBM 全局模型回测")


def test_report_writing():
    panel = _synthetic_panel(n_weeks=48)
    config = BacktestConfig(
        horizon=2,
        n_folds=2,
        min_train_weeks=32,
        seasonality=13,
        models=("naive", "ma4"),
        include_lgbm=False,
    )
    result = run_backtest(panel, config)
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_report(result, tmp, dataset_meta={"dataset": "synthetic"}, title="Synthetic")
        for name in ("markdown", "summary", "predictions"):
            assert paths[name].exists(), f"{name} 未生成"
        markdown = paths["markdown"].read_text(encoding="utf-8")
        assert "Overall metrics" in markdown and "naive" in markdown
        payload = json.loads(paths["summary"].read_text(encoding="utf-8"))
        assert payload["config"]["horizon"] == 2
        assert payload["overall"]
    print("[OK] Markdown/JSON/CSV 报告生成")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 1 forecasting tests")
    print("=" * 56)
    tests = [
        test_etl_cleaning_and_aggregation,
        test_metrics_known_values,
        test_baselines_output_shape,
        test_features_no_future_leakage,
        test_folds_and_backtest,
        test_report_writing,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All forecasting tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
