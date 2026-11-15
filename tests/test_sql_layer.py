"""Tests for the DuckDB/SQL demand warehouse."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.data.sql import DemandWarehouse, SQLWarehouseError  # noqa: E402


def _panel(path: Path) -> Path:
    frame = pd.DataFrame(
        {
            "sku": ["A", "A", "B", "B", "C"],
            "week": pd.to_datetime(
                ["2025-01-06", "2025-01-13", "2025-01-06", "2025-01-13", "2025-01-06"]
            ),
            "demand": [10, 20, 5, 15, 1],
            "orders": [2, 3, 1, 2, 1],
        }
    )
    frame.to_parquet(path, index=False)
    return path


def test_weekly_demand_and_top_skus(tmp_path: Path) -> None:
    path = _panel(tmp_path / "panel.parquet")
    with DemandWarehouse(path) as warehouse:
        weekly = warehouse.weekly_demand()
        assert list(weekly["demand"]) == [16, 35]
        top = warehouse.top_skus(2)
        assert list(top["sku"]) == ["A", "B"]
        assert list(top["demand"]) == [30, 20]


def test_demand_for_week_and_long(tmp_path: Path) -> None:
    path = _panel(tmp_path / "panel.parquet")
    with DemandWarehouse(path) as warehouse:
        week = warehouse.demand_for_week("2025-01-06")
        assert set(week["sku"]) == {"A", "B", "C"}
        assert int(week["demand"].sum()) == 16
        long = warehouse.demand_long()
        assert len(long) == 5
        assert set(long.columns) == {"week", "sku", "demand"}


def test_errors_are_explicit(tmp_path: Path) -> None:
    with pytest.raises(SQLWarehouseError):
        DemandWarehouse(tmp_path / "missing.parquet")
    path = _panel(tmp_path / "panel.parquet")
    with DemandWarehouse(path) as warehouse:
        with pytest.raises(SQLWarehouseError):
            warehouse.top_skus(0)
        with pytest.raises(SQLWarehouseError):
            warehouse.query("")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} SQL tests passed")
