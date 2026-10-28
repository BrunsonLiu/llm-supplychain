# -*- coding: utf-8 -*-
"""Run the rolling-origin backtest and write benchmark reports.

Examples:
  python scripts/run_backtest.py
  python scripts/run_backtest.py --horizon 8 --folds 5
  python scripts/run_backtest.py --no-lgbm --out-dir benchmarks/baselines
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.forecasting import (  # noqa: E402
    BacktestConfig,
    aggregate_view,
    evaluate_predictions,
    format_metric_table,
    run_backtest,
    write_report,
)
from supply.data import load_panel  # noqa: E402


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rolling-origin demand forecast backtest")
    parser.add_argument(
        "--panel",
        default=str(ROOT / "data" / "processed" / "online_retail_ii_weekly.parquet"),
        help="周度面板 parquet",
    )
    parser.add_argument("--meta", default=None, help="面板元数据 JSON（默认同名 .meta.json）")
    parser.add_argument("--out-dir", default=str(ROOT / "benchmarks"), help="报告输出目录")
    parser.add_argument("--horizon", type=int, default=13, help="预测步长（周）")
    parser.add_argument("--folds", type=int, default=4, help="滚动折数")
    parser.add_argument("--min-train-weeks", type=int, default=52, help="首折最小训练周数")
    parser.add_argument("--seasonality", type=int, default=52, help="季节周期")
    parser.add_argument("--models", default=None, help="逗号分隔的基线模型（默认全部）")
    parser.add_argument("--no-lgbm", action="store_true", help="跳过 LightGBM")
    parser.add_argument("--lgbm-rounds", type=int, default=1000, help="LightGBM 最大迭代轮数")
    parser.add_argument("--lgbm-early-stopping", type=int, default=50, help="LightGBM 早停轮数")
    parser.add_argument("--title", default="Demand forecasting benchmark (Online Retail II)")
    return parser.parse_args()


def main() -> None:
    _configure_stdout()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()

    panel_path = Path(args.panel)
    if not panel_path.exists():
        raise SystemExit(
            f"找不到面板: {panel_path}\n请先运行: python scripts/prepare_data.py"
        )
    meta_path = Path(args.meta) if args.meta else panel_path.with_suffix(".meta.json")
    meta = {}
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)

    panel, _ = load_panel(panel_path, meta_path if meta_path.exists() else None)
    weeks = panel["week"].nunique()
    print(f"面板: {panel['sku'].nunique()} SKU x {weeks} 周")

    models = tuple(m.strip() for m in args.models.split(",")) if args.models else None

    def build_config(folds: int) -> BacktestConfig:
        return BacktestConfig(
            horizon=args.horizon,
            n_folds=folds,
            min_train_weeks=args.min_train_weeks,
            seasonality=args.seasonality,
            models=models or BacktestConfig().models,
            include_lgbm=not args.no_lgbm,
            lgbm_num_boost_round=args.lgbm_rounds,
            lgbm_early_stopping=args.lgbm_early_stopping,
        )

    folds = args.folds
    while True:
        config = build_config(folds)
        try:
            result = run_backtest(panel, config)
            break
        except ValueError as exc:
            if folds <= 2:
                raise
            print(f"[warn] {exc} -> 尝试 {folds - 1} 折")
            folds -= 1

    paths = write_report(result, args.out_dir, dataset_meta=meta, title=args.title)

    overall = evaluate_predictions(result.predictions).sort_values("wmape")
    columns = ["model", "n", "wmape", "bias", "mae", "rmse", "rmsse"]
    columns = [col for col in columns if col in overall.columns]
    print("\n各模型指标（WMAPE 越低越好）:")
    print(format_metric_table(overall[columns]).to_string(index=False))

    aggregate = aggregate_view(result.predictions)
    aggregate["wmape"] = aggregate["wmape"].map(lambda v: f"{v:.2%}")
    aggregate["bias"] = aggregate["bias"].map(lambda v: f"{v:.2%}")
    print("\n仓库周度总量口径:")
    print(aggregate[["model", "weeks", "wmape", "bias"]].to_string(index=False))
    print("\n报告文件:")
    for name, path in paths.items():
        print(f"  {name}: {path}")


if __name__ == "__main__":
    main()
