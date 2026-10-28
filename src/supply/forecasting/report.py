"""Write Markdown, JSON, and CSV benchmark reports from backtest results."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .backtest import BacktestResult
from .metrics import format_metric_table, summarize

_METRIC_COLUMNS = ["model", "n", "wmape", "bias", "mae", "rmse", "rmsse"]
_HORIZON_ORDER = ["1-4", "5-8", "9-13", "14-26", "27+"]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if pd.isna(value):
        return None
    return value


def _md_table(frame: pd.DataFrame, floatfmt: str = ".3f") -> str:
    if frame.empty:
        return "_(empty)_"
    columns = [str(col) for col in frame.columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join("---" for _ in columns) + "|",
    ]
    for _, row in frame.iterrows():
        cells: List[str] = []
        for value in row:
            if isinstance(value, float):
                cells.append("—" if not math.isfinite(value) else format(value, floatfmt))
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                cells.append("—")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _format_overall(overall: pd.DataFrame) -> pd.DataFrame:
    ordered = overall.sort_values("wmape", na_position="last").reset_index(drop=True)
    formatted = format_metric_table(ordered)
    columns = [col for col in _METRIC_COLUMNS if col in formatted.columns]
    formatted = formatted[columns].astype(str)
    formatted.insert(0, "rank", range(1, len(formatted) + 1))
    return formatted


def _horizon_pivot(by_horizon: pd.DataFrame) -> pd.DataFrame:
    if by_horizon.empty:
        return by_horizon
    pivot = by_horizon.pivot(index="model", columns="horizon_bucket", values="wmape")
    ordered = [col for col in _HORIZON_ORDER if col in pivot.columns]
    pivot = pivot[ordered].map(lambda v: "—" if pd.isna(v) else f"{v:.2%}")
    pivot = pivot.reset_index()
    return pivot


def aggregate_view(predictions: pd.DataFrame) -> pd.DataFrame:
    """Planning-level view: sum the selected SKUs into one weekly volume."""
    weekly = (
        predictions.groupby(["model", "fold", "week"], as_index=False)
        .agg(actual=("actual", "sum"), pred=("pred", "sum"))
    )
    weekly["abs_err"] = (weekly["pred"] - weekly["actual"]).abs()
    weekly["err"] = weekly["pred"] - weekly["actual"]
    view = weekly.groupby("model", as_index=False).agg(
        weeks=("week", "size"),
        actual_sum=("actual", "sum"),
        abs_err_sum=("abs_err", "sum"),
        err_sum=("err", "sum"),
    )
    view["wmape"] = view["abs_err_sum"] / view["actual_sum"].replace(0, np.nan)
    view["bias"] = view["err_sum"] / view["actual_sum"].replace(0, np.nan)
    return view.sort_values("wmape").reset_index(drop=True)


def build_report(
    result: BacktestResult,
    dataset_meta: Optional[Dict[str, Any]] = None,
    title: str = "Demand forecasting benchmark",
) -> Tuple[Dict[str, Any], str]:
    """Return (summary JSON payload, Markdown text)."""
    summaries = summarize(result.predictions)
    overall = summaries["overall"]
    by_horizon = summaries.get("by_horizon", pd.DataFrame())
    by_fold = summaries.get("by_fold", pd.DataFrame())
    aggregate = aggregate_view(result.predictions)

    config = result.config
    folds = [
        {
            "fold": fold.index,
            "cutoff": fold.cutoff,
            "test_start": fold.test_start,
            "test_end": fold.test_end,
            "train_weeks": fold.train_weeks,
            "test_weeks": fold.test_weeks,
        }
        for fold in result.folds
    ]

    timings = (
        result.timings.groupby("model")["seconds"]
        .agg(mean_seconds="mean", total_seconds="sum")
        .reset_index()
        if not result.timings.empty
        else pd.DataFrame()
    )

    importance = pd.DataFrame()
    if result.feature_importance:
        last_fold = max(result.feature_importance)
        importance = result.feature_importance[last_fold].head(15).copy()

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "dataset": dataset_meta or {},
        "config": {
            "horizon": config.horizon,
            "n_folds": config.n_folds,
            "min_train_weeks": config.min_train_weeks,
            "min_train_nonzero_weeks": config.min_train_nonzero_weeks,
            "seasonality": config.seasonality,
            "models": list(config.models),
            "include_lgbm": config.include_lgbm,
        },
        "folds": _json_safe(folds),
        "overall": _json_safe(overall.to_dict(orient="records")),
        "aggregate_volume": _json_safe(aggregate.to_dict(orient="records")),
        "by_horizon": _json_safe(by_horizon.to_dict(orient="records")),
        "by_fold": _json_safe(by_fold.to_dict(orient="records")),
        "timings": _json_safe(timings.to_dict(orient="records")),
        "feature_importance": _json_safe(importance.to_dict(orient="records")),
    }

    best = overall.sort_values("wmape").iloc[0] if not overall.empty else None
    lines = [f"# {title}", ""]
    lines.append(f"- Generated: `{summary['generated_at']}`")
    if dataset_meta:
        lines.append(
            f"- Dataset: `{dataset_meta.get('dataset', 'n/a')}` "
            f"({dataset_meta.get('weeks', '?')} weeks, "
            f"{dataset_meta.get('skus_selected', '?')} SKUs)"
        )
        lines.append(
            f"- Period: `{dataset_meta.get('start_week', '?')}` to "
            f"`{dataset_meta.get('end_week', '?')}`"
        )
    lines.append(
        f"- Backtest: {config.n_folds} rolling folds x horizon {config.horizon}, "
        f"min train {config.min_train_weeks} weeks"
    )
    if best is not None:
        lines.append(
            f"- Best model by WMAPE: **{best['model']}** "
            f"({best['wmape']:.2%})"
        )
    lines.extend(["", "## Overall metrics", "", _md_table(_format_overall(overall)), ""])

    aggregate_table = aggregate.copy()
    aggregate_table["wmape"] = aggregate_table["wmape"].map(lambda v: f"{v:.2%}")
    aggregate_table["bias"] = aggregate_table["bias"].map(lambda v: f"{v:.2%}")
    aggregate_table = aggregate_table[["model", "weeks", "wmape", "bias"]]
    lines.extend(
        [
            "## Aggregate volume (planning-level)",
            "",
            "Weekly demand summed across the selected SKUs. This is the volume view "
            "used for warehouse capacity and labor planning; SKU-level errors partially cancel.",
            "",
            _md_table(aggregate_table),
            "",
        ]
    )

    lines.extend(["## WMAPE by horizon bucket", "", _md_table(_horizon_pivot(by_horizon)), ""])

    if not by_fold.empty:
        fold_view = (
            by_fold.sort_values(["model", "fold"])[["model", "fold", "wmape", "bias", "rmsse"]]
            .copy()
        )
        fold_view["wmape"] = fold_view["wmape"].map(lambda v: f"{v:.2%}")
        fold_view["bias"] = fold_view["bias"].map(lambda v: f"{v:.2%}")
        lines.extend(["## WMAPE by fold", "", _md_table(fold_view), ""])

    if not importance.empty:
        lines.extend(
            ["## LightGBM feature importance (latest fold, top 15)", "", _md_table(importance), ""]
        )

    if not timings.empty:
        timing_view = timings.copy()
        timing_view["mean_seconds"] = timing_view["mean_seconds"].round(2)
        timing_view["total_seconds"] = timing_view["total_seconds"].round(2)
        lines.extend(["## Training time", "", _md_table(timing_view), ""])

    lines.extend(
        [
            "## Notes",
            "",
            "- WMAPE and bias are demand-weighted; RMSSE uses the M5 seasonal-naive scale.",
            "- Baselines include naive, seasonal-naive, moving averages, Croston-SBA (intermittent), "
            "and Holt. Holt-Winters needs two full seasonal cycles, which this two-year dataset "
            "cannot provide at every fold, so it is not in the default lineup.",
            "- LightGBM is a single global direct multi-horizon model; lag and rolling features are "
            "shifted by one week to prevent leakage.",
            "- Same-week-last-year anchors are added as features only when they have training "
            "coverage in that fold, so trees never split on untrained missing values.",
            "- SKUs with fewer than "
            f"{config.min_train_nonzero_weeks} non-zero weeks in a fold's training window are "
            "excluded from that fold; new-product launches need a separate process.",
            "- A fold whose test window crosses a holiday or level shift is dominated by that "
            "shift; read the by-fold table before comparing models.",
            "- Online Retail II contains demand, price, and calendar only. Inventory, lead time, and "
            "warehouse cost are introduced later as an explicit assumption layer.",
            "",
        ]
    )
    return summary, "\n".join(lines)


def write_report(
    result: BacktestResult,
    out_dir: str | Path,
    dataset_meta: Optional[Dict[str, Any]] = None,
    title: str = "Demand forecasting benchmark",
) -> Dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, markdown = build_report(result, dataset_meta=dataset_meta, title=title)

    paths = {
        "markdown": out_dir / "REPORT.md",
        "summary": out_dir / "backtest_summary.json",
        "predictions": out_dir / "backtest_predictions.csv",
    }
    paths["markdown"].write_text(markdown, encoding="utf-8")
    with open(paths["summary"], "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    result.predictions.to_csv(paths["predictions"], index=False)

    return paths
