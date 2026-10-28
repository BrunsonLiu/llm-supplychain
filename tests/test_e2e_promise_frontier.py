"""Week-23 tests: promise-service frontier and dominance."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_promise_frontier_report,
    pareto_frontier,
    service_frontiers,
    summarize_frontier,
    write_promise_frontier_report,
)


def test_pareto_dominance_and_annotation() -> None:
    rows = [
        {"quote_policy": "a", "quoted_otif_mean": 0.8,
         "static_sla_otif_mean": 0.8, "fill_mean": 0.8,
         "avg_promise_days": 4.0},
        {"quote_policy": "b", "quoted_otif_mean": 0.7,
         "static_sla_otif_mean": 0.7, "fill_mean": 0.7,
         "avg_promise_days": 5.0},
        {"quote_policy": "c", "quoted_otif_mean": 0.8,
         "static_sla_otif_mean": 0.8, "fill_mean": 0.8,
         "avg_promise_days": 3.0},
    ]
    annotated = {row["quote_policy"]: row for row in pareto_frontier(rows)}
    assert annotated["a"]["pareto"] is False
    assert annotated["a"]["dominated_by"] == "c"
    assert annotated["b"]["pareto"] is False
    assert annotated["c"]["pareto"] is True


def test_service_frontiers_disagree_on_atp() -> None:
    rows = [
        {"quote_policy": "static", "avg_promise_days": 3.1,
         "quoted_otif_mean": 0.868, "static_sla_otif_mean": 0.868},
        {"quote_policy": "atp", "avg_promise_days": 3.62,
         "quoted_otif_mean": 0.938, "static_sla_otif_mean": 0.845},
    ]
    annotated = {row["quote_policy"]: row for row in service_frontiers(rows)}
    assert annotated["static"]["static_pareto"] is True
    assert annotated["atp"]["static_pareto"] is False
    assert annotated["atp"]["static_dominated_by"] == "static"
    assert annotated["atp"]["quoted_pareto"] is True


def test_summarize_frontier_keeps_both_service_lenses() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "daily_1d", "quote_policy": "static", "seed": 1,
             "e2e_otif_rate": 0.8, "static_sla_otif_rate": 0.8,
             "avg_promise_days": 3.1, "fast_share": 0.3, "fill_rate": 0.9,
             "late_orders": 20, "backlog_units": 100, "avg_delivery_day": 4.0,
             "replenished_units": 50},
            {"policy": "daily_1d", "quote_policy": "static", "seed": 2,
             "e2e_otif_rate": 0.9, "static_sla_otif_rate": 0.9,
             "avg_promise_days": 3.1, "fast_share": 0.3, "fill_rate": 0.9,
             "late_orders": 20, "backlog_units": 100, "avg_delivery_day": 4.0,
             "replenished_units": 50},
            {"policy": "daily_1d", "quote_policy": "atp", "seed": 1,
             "e2e_otif_rate": 0.95, "static_sla_otif_rate": 0.85,
             "avg_promise_days": 4.0, "fast_share": 0.0, "fill_rate": 0.95,
             "late_orders": 5, "backlog_units": 50, "avg_delivery_day": 4.4,
             "replenished_units": 50},
        ]
    )
    summary = summarize_frontier(frame)
    static = summary[summary["quote_policy"] == "static"].iloc[0]
    assert abs(static["quoted_otif_mean"] - 0.85) < 1e-9
    assert abs(static["static_sla_otif_mean"] - 0.85) < 1e-9
    assert set(summary.columns) >= {
        "quoted_otif_mean", "static_sla_otif_mean", "avg_promise_days"
    }


def test_report_exposes_frontier_and_dominance() -> None:
    summary = [
        {"policy": "single_week", "quote_policy": "static",
         "label": "固定 2/3/5", "quoted_otif_mean": 0.52,
         "static_sla_otif_mean": 0.52, "avg_promise_days": 3.1,
         "fast_share": 0.3, "fill_mean": 0.83, "late_orders_mean": 191,
         "backlog_units": 5597, "static_pareto": False,
         "quoted_pareto": False},
        {"policy": "daily_1d", "quote_policy": "static",
         "label": "固定 2/3/5", "quoted_otif_mean": 0.868,
         "static_sla_otif_mean": 0.868, "avg_promise_days": 3.1,
         "fast_share": 0.3, "fill_mean": 0.98, "late_orders_mean": 51,
         "backlog_units": 672, "static_pareto": True,
         "quoted_pareto": True},
        {"policy": "daily_1d", "quote_policy": "atp",
         "label": "ATP", "quoted_otif_mean": 0.938,
         "static_sla_otif_mean": 0.845, "avg_promise_days": 3.62,
         "fast_share": 0.0, "fill_mean": 0.987, "late_orders_mean": 25,
         "backlog_units": 444, "static_pareto": False,
         "static_dominated_by": "static", "quoted_pareto": True},
        {"policy": "daily_1d", "quote_policy": "all_5",
         "label": "全部 5 天", "quoted_otif_mean": 0.95,
         "static_sla_otif_mean": 0.84, "avg_promise_days": 5.0,
         "fast_share": 0.0, "fill_mean": 0.985, "late_orders_mean": 20,
         "backlog_units": 503, "static_pareto": False,
         "static_dominated_by": "static", "quoted_pareto": True},
    ]
    payload = {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28"},
        "settings": {"seeds": 30, "quote_policies": ["static", "atp", "all_5"],
                     "milp_time": 8},
        "order_days": {"0": 66, "1": 73},
        "summary": summary,
        "limitations": ["Pareto 只在本次策略集合内成立"],
    }
    text = build_promise_frontier_report(payload)
    assert "原 SLA 前沿" in text
    assert "quoted 前沿" in text
    assert "被 static 支配" in text
    assert "ATP is not on the original-SLA frontier" in text
    assert "Pareto 只在本次策略集合内成立" in text


def test_write_frontier_report(tmp_path: Path) -> None:
    payload = {
        "dataset": {"orders": 1, "lines": 1, "units": 1, "week": "2011-11-28"},
        "settings": {"seeds": 1, "quote_policies": [], "milp_time": 1},
        "order_days": {"0": 1},
        "summary": [],
        "limitations": [],
    }
    paths = write_promise_frontier_report(payload, tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 23" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_frontier_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("5 promise frontier tests passed")
