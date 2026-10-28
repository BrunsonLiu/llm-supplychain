"""Week-20 tests: daily rolling allocation joined to pick/dispatch."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    E2E_ROLLING_POLICIES,
    E2EInstance,
    PickPlan,
    TIER_CUTOFFS,
    build_rolling_e2e_report,
    paired_e2e_delta,
    summarize_flow,
)
from supply.e2e.dispatch import DispatchCell  # noqa: E402
from supply.e2e.rolling_e2e import PreparedDay, _dispatch_instance  # noqa: E402
from supply.fulfillment import FulfillmentInstance  # noqa: E402
from supply.network import WarehouseLayout  # noqa: E402


def _instance(promises=(1, 4)) -> E2EInstance:
    fulfillment = FulfillmentInstance(
        order_ids=["O0", "O1"],
        destinations=["United Kingdom", "Germany"],
        line_order=np.array([0, 1]),
        line_sku=np.array([0, 1]),
        line_qty=np.array([10, 10]),
        sku_names=["A", "B"],
        dc_names=["North", "South"],
        stock=np.array([[20, 0], [0, 20]], dtype=np.int64),
        dc_capacity=np.array([50, 50], dtype=np.int64),
        ship_cost=np.ones((2, 2), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.full((2, 2), 2, dtype=np.int64),
        promise_days=np.array(promises, dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )
    pick = PickPlan(
        tier_of={"O0": "express", "O1": "economy"},
        cutoff_of={
            "O0": TIER_CUTOFFS["express"],
            "O1": TIER_CUTOFFS["economy"],
        },
        arrival_of={"O0": 0.0, "O1": 0.0},
        tier_onsite={"express": 1.0, "standard": 1.0, "economy": 1.0},
        tier_windows={"express": 0.0, "standard": 0.0, "economy": 0.0},
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=WarehouseLayout(n_aisles=1, n_bays=4),
        slots={"A": (1, 1, 0), "B": (1, 2, 0)},
        pick=pick,
    )


def test_policy_set() -> None:
    assert E2E_ROLLING_POLICIES == ("none", "daily_1d", "daily_2d")


def test_dispatch_cell_accepts_same_day_window() -> None:
    cell = DispatchCell(
        key="daily", label="daily", policy="immediate", max_days=0
    )
    assert cell.config().max_days == 0
    assert cell.as_dict()["max_days"] == 0


def test_dispatch_instance_maps_residual_promises_to_tiers() -> None:
    instance = _instance(promises=(1, 4))
    prepared = PreparedDay(
        day=0,
        instance=instance,
        allocation=None,  # type: ignore[arg-type]
        lines=np.array([0, 1]),
        open_orders=np.array([0, 1]),
    )
    shifted = _dispatch_instance(prepared)
    assert shifted.fulfillment.promise_days.tolist() == [2, 5]


def test_summarize_and_paired_delta() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "none", "seed": 1, "e2e_otif_rate": 0.2, "fill_rate": 0.8,
             "late_orders": 8, "backlog_units": 10, "avg_delivery_day": 3.0,
             "replenished_units": 0},
            {"policy": "none", "seed": 2, "e2e_otif_rate": 0.4, "fill_rate": 0.8,
             "late_orders": 6, "backlog_units": 10, "avg_delivery_day": 3.0,
             "replenished_units": 0},
            {"policy": "daily_1d", "seed": 1, "e2e_otif_rate": 0.5, "fill_rate": 0.9,
             "late_orders": 5, "backlog_units": 4, "avg_delivery_day": 2.5,
             "replenished_units": 10},
            {"policy": "daily_1d", "seed": 2, "e2e_otif_rate": 0.7, "fill_rate": 0.9,
             "late_orders": 3, "backlog_units": 4, "avg_delivery_day": 2.5,
             "replenished_units": 10},
        ]
    )
    summary = summarize_flow(frame).set_index("policy")
    assert abs(summary.loc["none", "e2e_otif_mean"] - 0.3) < 1e-9
    assert abs(summary.loc["daily_1d", "e2e_otif_mean"] - 0.6) < 1e-9
    delta = paired_e2e_delta(frame, "daily_1d", "none")
    assert abs(delta["mean"] - 0.3) < 1e-9
    assert delta["win"] == 1.0


def test_report_mentions_scope_and_baseline() -> None:
    payload = {
        "dataset": {"orders": 10, "lines": 20, "units": 30, "week": "2011-11-28"},
        "settings": {"milp_time": 8, "baseline_milp_time": 60, "stock_factor": 0.85,
                     "seeds": 2},
        "order_days": {"0": 5, "1": 5},
        "summary": [
            {"policy": "single_week", "label": "单周", "seeds": 2,
             "e2e_otif_mean": 0.3, "e2e_otif_p10": 0.2, "e2e_otif_p50": 0.3,
             "e2e_otif_p90": 0.4, "fill_mean": 0.8, "late_orders_mean": 6,
             "backlog_units": 10, "avg_delivery_day": 2.0,
             "replenished_units": 0},
            {"policy": "daily_1d", "label": "每日1天", "seeds": 2,
             "e2e_otif_mean": 0.5, "e2e_otif_p10": 0.4, "e2e_otif_p50": 0.5,
             "e2e_otif_p90": 0.6, "fill_mean": 0.9, "late_orders_mean": 4,
             "backlog_units": 5, "avg_delivery_day": 2.1,
             "replenished_units": 10},
        ],
        "paired": [{"left": "daily_1d", "right": "single_week", "n": 2,
                    "mean": 0.2, "ci95": 0.0, "win": 1.0, "loss": 0.0,
                    "tie": 0.0}],
        "limitations": ["只重放分单到发车"],
    }
    text = build_rolling_e2e_report(payload)
    assert "picking usually clears the last departure" in text
    assert "只重放分单到发车" in text
    assert "50.0%" in text


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            func()
            print(f"[OK] {name}")
    print("6 rolling e2e tests passed")
