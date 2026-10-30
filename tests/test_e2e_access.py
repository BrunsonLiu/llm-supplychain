"""Week-41 tests: demand-weighted stock placement MILP."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    E2EInstance,
    apply_target,
    build_access_report,
    history_access,
    moved_units,
    oracle_access,
    placement_milp,
    summarize_access,
    write_access_report,
)
from supply.fulfillment import FulfillmentInstance  # noqa: E402


def _instance() -> E2EInstance:
    fulfillment = FulfillmentInstance(
        order_ids=["o1", "o2"],
        destinations=["DE", "FR"],
        line_order=np.array([0, 1]),
        line_sku=np.array([0, 1]),
        line_qty=np.array([5, 5]),
        sku_names=["s1", "s2"],
        dc_names=["d1", "d2"],
        stock=np.array([[5, 0], [0, 5]], dtype=np.int64),
        dc_capacity=np.array([100, 100], dtype=np.int64),
        ship_cost=np.zeros((2, 2)),
        fixed_ship_cost=0.0,
        transit_days=np.array([[1, 1], [3, 3]], dtype=np.int64),
        promise_days=np.array([2, 2], dtype=np.int64),
        late_penalty_per_unit_day=1.0,
        unmet_penalty_per_unit=10.0,
        meta={},
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=None,
        slots={},
        pick=None,
    )


def _row(policy: str, target: float, seed: int = 1):
    return {
        "policy": policy,
        "label": policy,
        "accepted_orders": 400.0,
        "accepted_otif_rate": 0.985,
        "target_accepted_otif_rate": target,
        "rest_accepted_otif_rate": 0.986,
        "accepted_fill_rate": 0.996,
        "accepted_backlog_units": 150.0,
        "avg_delivery_day": 3.51,
        "moved_units": 0.0,
        "milp_status": "OPTIMAL",
        "seed": seed,
    }


def test_oracle_demand_counts_on_time_dcs() -> None:
    demand = oracle_access(_instance())
    assert demand.source == "oracle"
    assert demand.units.shape == (2, 2)
    assert demand.units[0, 0] == 5.0 and demand.units[0, 1] == 5.0
    assert demand.units[1].sum() == 0.0
    print("[OK] oracle 可达需求只统计承诺内 DC")


def test_oracle_demand_partitions_instead_of_double_counting() -> None:
    from dataclasses import replace

    instance = _instance()
    both = replace(
        instance,
        fulfillment=replace(
            instance.fulfillment,
            transit_days=np.array([[1, 1], [1, 1]], dtype=np.int64),
        ),
    )
    demand = oracle_access(both)
    assert demand.units.sum() == 10.0
    assert demand.units[0, 0] == 5.0 and demand.units[0, 1] == 5.0
    print("[OK] oracle 需求按最佳 DC 分区，不重复计数")


def test_placement_milp_preserves_total_and_moves_to_accessible_dc() -> None:
    instance = _instance()
    target = placement_milp(instance, oracle_access(instance))
    assert target.optimal, target.status
    assert np.array_equal(target.stock.sum(axis=0), instance.fulfillment.stock.sum(axis=0))
    assert target.stock[0, 1] == 5
    assert target.stock[1, 1] == 0
    assert target.moved_units == 5
    assert target.coverage == 1.0
    print("[OK] 布点 MILP 保持总量并优先可达 DC")


def test_placement_milp_respects_share_bounds() -> None:
    instance = _instance()
    target = placement_milp(
        instance,
        oracle_access(instance),
        min_share=0.2,
        max_share=0.8,
    )
    by_dc = target.stock.sum(axis=1)
    assert by_dc.min() >= 2
    assert by_dc.max() <= 8
    assert target.stock.sum() == 10
    print("[OK] 布点 MILP 遵守 DC 份额上下界")


def test_load_aware_placement_caps_stock_implied_pick_minutes() -> None:
    instance = _instance()
    target = placement_milp(
        instance,
        oracle_access(instance),
        pick_minutes_per_unit=0.1,
        pick_capacity=0.6,
        pick_load_penalty=10_000_000,
    )
    assert target.stock.sum() == 10
    assert target.peak_pick_minutes <= 0.61
    assert target.overload_minutes <= 1e-9
    assert target.pick_capacity == 0.6
    print("[OK] 负荷感知布点把 stock-implied 拣选分钟压在容量内")


def test_apply_target_keeps_sku_totals() -> None:
    instance = _instance()
    target = placement_milp(instance, oracle_access(instance))
    updated = apply_target(instance, target)
    assert np.array_equal(
        updated.fulfillment.stock.sum(axis=0),
        instance.fulfillment.stock.sum(axis=0),
    )
    assert updated.fulfillment.stock[0, 1] == 5
    print("[OK] apply_target 只替换库存矩阵")


def test_history_demand_uses_prior_weeks_only() -> None:
    clean = pd.DataFrame(
        {
            "invoice_date": pd.to_datetime(
                ["2011-11-07", "2011-11-07", "2011-11-14", "2011-11-14"]
            ),
            "country": ["DE", "FR", "DE", "FR"],
            "sku": ["s1", "s2", "s1", "s2"],
            "quantity": [10, 20, 10, 20],
        }
    )
    demand = history_access(
        clean,
        _instance(),
        week=pd.Timestamp("2011-11-28"),
        lookback_weeks=2,
    )
    assert demand.source == "history"
    assert demand.units.shape == (2, 2)
    # Two prior weeks -> 10 and 20 units / 2 weeks; only d1 is on-time.
    assert abs(demand.units[0, 0] - 5.0) < 1e-9
    assert abs(demand.units[0, 1] - 10.0) < 1e-9
    assert demand.units[1].sum() == 0.0
    print("[OK] 历史需求只读前 lookback 周")


def test_moved_units_rejects_non_conserved_stock() -> None:
    with np.testing.assert_raises(ValueError):
        moved_units(
            np.array([[5, 0], [0, 5]]),
            np.array([[5, 0], [0, 4]]),
        )
    print("[OK] 非守恒库存被 moved_units 拒绝")


def test_summarize_access_averages_seeds() -> None:
    frame = pd.DataFrame(
        [
            _row("access_history", 0.95, seed=1),
            _row("access_history", 0.97, seed=2),
        ]
    )
    summary = summarize_access(frame)
    row = summary.iloc[0]
    assert row["policy"] == "access_history"
    assert abs(row["target_accepted_otif_mean"] - 0.96) < 1e-9
    print("[OK] access 汇总按 seed 取均值")


def test_report_and_writer(tmp_path: Path) -> None:
    payload = {
        "dataset": {"orders": 400, "units": 33060, "week": "2011-11-28"},
        "settings": {"seeds": 30, "solver_time": 10.0, "lookback_weeks": 6},
        "summary": [
            {
                "policy": "baseline",
                "label": "基线无调拨",
                "target_accepted_otif_mean": 0.95,
                "rest_accepted_otif_mean": 0.986,
                "accepted_otif_mean": 0.985,
                "accepted_backlog_units": 170.0,
                "accepted_fill_rate": 0.995,
                "avg_delivery_day": 3.52,
                "moved_units_mean": 0.0,
                "milp_status": "—",
            },
            {
                "policy": "access_oracle",
                "label": "oracle 可达需求布点",
                "target_accepted_otif_mean": 0.975,
                "rest_accepted_otif_mean": 0.986,
                "accepted_otif_mean": 0.988,
                "accepted_backlog_units": 140.0,
                "accepted_fill_rate": 0.996,
                "avg_delivery_day": 3.50,
                "moved_units_mean": 2100.0,
                "milp_status": "OPTIMAL",
            },
        ],
        "rows": [],
        "limitations": ["oracle 使用本周实际订单，是上界"],
    }
    text = build_access_report(payload)
    assert "Week 41" in text
    assert "access_oracle" in text
    assert "oracle" in text.lower()
    paths = write_access_report(payload, tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 41" in paths["report"].read_text(encoding="utf-8")
    load_paths = write_access_report(payload, tmp_path, stem="ACCESS_LOAD")
    assert load_paths["report"].name == "ACCESS_LOAD_REPORT.md"
    assert load_paths["summary"].name == "access_load_summary.json"
    print("[OK] access 报告与 JSON 落盘")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_report_and_writer":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("10 access placement tests passed")
