"""Tests for Week-19 rolling allocation helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    FLOW_DAYS,
    ROLLING_POLICIES,
    build_rolling_report,
    order_day_map,
    rolling_cells,
)
from supply.e2e.rolling import _replenish  # noqa: E402


def test_order_day_map_uses_weekday_and_folds_weekend() -> None:
    instance = SimpleNamespace(
        order_ids=["A", "B", "C", "D"],
        n_orders=4,
    )
    clean = pd.DataFrame(
        {
            "invoice": ["A", "B", "C", "D"],
            "invoice_date": [
                pd.Timestamp("2011-11-28 09:00"),  # Monday
                pd.Timestamp("2011-11-30 09:00"),  # Wednesday
                pd.Timestamp("2011-12-03 09:00"),  # Saturday
                pd.Timestamp("2011-12-04 09:00"),  # Sunday
            ],
        }
    )
    assert order_day_map(instance, clean).tolist() == [0, 2, 4, 4]


def test_flow_days_and_policies() -> None:
    assert FLOW_DAYS == 5
    assert "daily_1d" in ROLLING_POLICIES
    assert len(ROLLING_POLICIES) == len(set(ROLLING_POLICIES))
    cells = rolling_cells()
    assert len(cells) == len(ROLLING_POLICIES)
    assert all(cell.policy == cell.key for cell in cells)


def test_replenish_none_does_nothing() -> None:
    pipeline = {}
    stock = np.array([[0, 0], [0, 0]])
    _replenish("none", 0, stock, stock + 10, 5, pipeline, 0.1)
    assert pipeline == {}


def test_replenish_one_day_lead() -> None:
    pipeline = {}
    stock = np.zeros((2, 2))
    initial = np.full((2, 2), 10)
    _replenish("daily_1d", 0, stock, initial, 5, pipeline, 0.1)
    assert set(pipeline) == {1}
    assert np.array_equal(pipeline[1], np.full((2, 2), 8))


def test_replenish_two_day_lead() -> None:
    pipeline = {}
    stock = np.zeros((2, 2))
    initial = np.full((2, 2), 10)
    _replenish("daily_2d", 0, stock, initial, 5, pipeline, 0.1)
    assert set(pipeline) == {2}
    assert np.array_equal(pipeline[2], np.full((2, 2), 6))


def test_replenish_safety_rounds_up() -> None:
    pipeline = {}
    stock = np.zeros((2, 2))
    initial = np.full((2, 2), 10)
    _replenish(
        "daily_1d_safety", 0, stock, initial, 5, pipeline, 0.10
    )
    assert np.array_equal(pipeline[1], np.full((2, 2), 9))


def test_replenish_batch_every_two_days() -> None:
    pipeline = {}
    stock = np.zeros((2, 2))
    initial = np.full((2, 2), 10)
    _replenish("batch_2d", 0, stock, initial, 5, pipeline, 0.1)
    assert pipeline == {}
    _replenish("batch_2d", 1, stock, initial, 5, pipeline, 0.1)
    assert np.array_equal(pipeline[2], np.full((2, 2), 6))


def test_report_handles_baseline_without_days() -> None:
    payload = {
        "dataset": {"orders": 10, "lines": 20, "units": 30, "week": "2011-11-28"},
        "settings": {"milp_time": 12, "stock_factor": 0.85, "safety": 0.1},
        "order_days": {"0": 5, "1": 5},
        "summary": [
            {
                "policy": "single_week",
                "label": "单周快照",
                "fill_rate": 0.8,
                "otif_rate": 0.4,
                "late_units": 0,
                "backlog_units": 10,
                "replenished_units": 0,
                "stockout_days": 0,
                "avg_inventory_units": 100,
            },
            {
                "policy": "none",
                "label": "不补货",
                "days": 2,
                "fill_rate": 0.7,
                "otif_rate": 0.3,
                "late_units": 1,
                "backlog_units": 20,
                "replenished_units": 0,
                "stockout_days": 2,
                "avg_inventory_units": 90,
            },
        ],
        "by_order_day": [
            {"day": 0, "label": "不补货", "otif_rate": 0.5},
            {"day": 1, "label": "不补货", "otif_rate": 0.1},
        ],
        "limitations": ["scope"],
    }
    report = build_rolling_report(payload)
    assert "Weekly snapshot vs rolling flow" in report
    assert "Findings" in report
    assert "单周快照" in report
    assert "不补货" in report


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} rolling tests passed")
