"""Week-35 tests: inbound arrival expedite report and priority arrivals."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    ArrivalCurve,
    E2EInstance,
    PickPlan,
    build_arrival_report,
    rebuild_arrivals,
    summarize_arrival,
    write_arrival_report,
)
from supply.fulfillment import FulfillmentInstance  # noqa: E402
from supply.network.warehouse import WarehouseLayout  # noqa: E402


def _row(**overrides):
    base = {
        "policy": "atp_3_top10_base",
        "label": "Top10 破例 · 基准到达",
        "target_label": "Top 10%",
        "orders": 400,
        "accepted_orders": 310.0,
        "lost_orders": 90.0,
        "accepted_rate": 0.775,
        "accepted_units": 15000,
        "lost_units": 18060,
        "demand_revenue": 170467.0,
        "accepted_revenue": 133800.0,
        "lost_revenue": 36667.0,
        "revenue_accept_rate": 0.785,
        "accepted_otif_mean": 0.99,
        "accepted_static_sla_mean": 0.935,
        "all_otif_mean": 0.767,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.925,
        "target_all_otif_mean": 0.925,
        "rest_accepted_otif_mean": 1.0,
        "departures": 49.1,
        "mean_wait_minutes": 218.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_3_top10_base"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            _row(),
            _row(policy="atp_3_top10_target_early",
                 label="Top10 破例 · 目标提前到达", departures=46.0),
            _row(policy="atp_3_top10_all_early",
                 label="Top10 破例 · 全部提前到达", departures=34.5),
            _row(policy="atp_3_top25_base", target_label="Top 25%",
                 target_accepted_otif_mean=0.93),
            _row(policy="atp_3_top25_target_early", target_label="Top 25%",
                 target_accepted_otif_mean=0.93, departures=54.3),
            _row(policy="atp_3_top25_all_early", target_label="Top 25%",
                 target_accepted_otif_mean=0.93, departures=44.6),
        ],
        "rows": [],
        "limitations": ["提前到达只改入库时间戳"],
    }


def _instance() -> E2EInstance:
    n = 4
    fulfillment = FulfillmentInstance(
        order_ids=[f"O{index}" for index in range(n)],
        destinations=["United Kingdom"] * n,
        line_order=np.arange(n),
        line_sku=np.zeros(n, dtype=np.int64),
        line_qty=np.full(n, 2, dtype=np.int64),
        sku_names=["A"],
        dc_names=["North"],
        stock=np.full((1, 1), 100, dtype=np.int64),
        dc_capacity=np.full(1, 10_000, dtype=np.int64),
        ship_cost=np.ones((1, n), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.ones((1, n), dtype=np.int64),
        promise_days=np.full(n, 3, dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=100.0,
        meta={},
    )
    pick = PickPlan(
        tier_of={f"O{index}": "standard" for index in range(n)},
        cutoff_of={f"O{index}": 480 for index in range(n)},
        arrival_of={f"O{index}": 0.0 for index in range(n)},
        tier_onsite={"express": 0.0, "standard": 0.0, "economy": 0.0},
        tier_windows={"express": 120.0, "standard": 360.0, "economy": 480.0},
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=WarehouseLayout(n_aisles=1, n_bays=4),
        slots={"A": (1, 1, 0)},
        pick=pick,
        pickers_per_dc=1,
        shift_minutes=600.0,
        meta={"assumptions": ["合成测试实例"]},
    )


def test_summarize_arrival_keeps_policy_row() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10_all_early", "seed": 1, "orders": 2,
             "accepted_orders": 2, "lost_orders": 0, "accepted_rate": 1.0,
             "accepted_units": 10, "lost_units": 0, "demand_revenue": 100.0,
             "accepted_revenue": 100.0, "lost_revenue": 0.0,
             "revenue_accept_rate": 1.0, "accepted_otif_rate": 1.0,
             "accepted_static_sla_otif_rate": 1.0, "e2e_otif_rate": 1.0,
             "target_accepted_orders": 1, "target_accepted_otif_rate": 1.0,
             "target_all_otif_rate": 1.0, "rest_accepted_otif_rate": 1.0,
             "departures": 2, "mean_wait_minutes": 10.0},
        ]
    )
    summary = summarize_arrival(frame)
    assert summary.iloc[0]["departures"] == 2.0


def test_report_marks_real_arrival_manipulation() -> None:
    text = build_arrival_report(_payload())
    assert "same prepared flow" in text
    assert "arrival manipulation was real" in text
    assert "stock/allocation" in text
    assert "提前到达只改" in text


def test_write_arrival_report(tmp_path: Path) -> None:
    paths = write_arrival_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 35" in paths["report"].read_text(encoding="utf-8")


def test_priority_arrivals_are_onsite_at_zero() -> None:
    instance = _instance()
    curve = ArrivalCurve(
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        start_hour=8,
        end_hour=18,
    )
    plain = rebuild_arrivals(instance, 7, arrival_curve=curve)
    boosted = rebuild_arrivals(
        instance, 7, arrival_curve=curve, priority_orders=[1, 3]
    )
    assert all(value > 0 for value in plain.pick.arrival_of.values())
    assert boosted.pick.arrival_of["O1"] == 0.0
    assert boosted.pick.arrival_of["O3"] == 0.0
    assert boosted.pick.arrival_of["O0"] > 0.0


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_arrival_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 arrival tests passed")
