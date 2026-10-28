"""Tests for the Week-18 promise-quoting policies."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    QUOTE_POLICIES,
    quote_frontier,
    quote_promises,
    tier_for_days,
)


def _fulfillment(transit, stock):
    from supply.fulfillment import FulfillmentInstance

    orders = 1
    return FulfillmentInstance(
        order_ids=["A"],
        destinations=["UK"],
        line_order=np.array([0]),
        line_sku=np.array([0]),
        line_qty=np.array([1]),
        sku_names=["s"],
        dc_names=["D1", "D2"],
        stock=np.asarray(stock, dtype=np.int64),
        dc_capacity=np.array([10, 10]),
        ship_cost=np.zeros((2, orders)),
        fixed_ship_cost=0.0,
        transit_days=np.asarray(transit, dtype=np.int64),
        promise_days=np.array([3], dtype=np.int64),
        late_penalty_per_unit_day=1.0,
        unmet_penalty_per_unit=10.0,
        meta={},
    )


def _instance(transit, stock):
    fulfillment = _fulfillment(transit, stock)
    return SimpleNamespace(fulfillment=fulfillment, n_orders=1)


def test_tier_mapping() -> None:
    assert tier_for_days(1) == 2
    assert tier_for_days(2) == 2
    assert tier_for_days(2.9) == 3
    assert tier_for_days(3) == 3
    assert tier_for_days(4) == 5
    assert tier_for_days(9) == 5


def test_all_policies_are_exported() -> None:
    assert "atp" in QUOTE_POLICIES
    assert "all_5" in QUOTE_POLICIES
    assert len(set(QUOTE_POLICIES)) == len(QUOTE_POLICIES)


def test_atp_quotes_two_when_fast_stock_exists() -> None:
    instance = _instance([[1], [3]], [[1], [0]])
    assert quote_promises(instance, "atp")[0] == 2


def test_atp_quotes_five_without_any_stock() -> None:
    instance = _instance([[1], [3]], [[0], [0]])
    assert quote_promises(instance, "atp")[0] == 5


def test_atp_single_line_uses_fastest_dc() -> None:
    instance = _instance([[1], [3]], [[1], [0]])
    assert quote_promises(instance, "atp")[0] == 2


def test_atp_multi_line_uses_slowest_leg() -> None:
    from supply.fulfillment import FulfillmentInstance

    fulfillment = FulfillmentInstance(
        order_ids=["A"],
        destinations=["UK"],
        line_order=np.array([0, 0]),
        line_sku=np.array([0, 1]),
        line_qty=np.array([1, 1]),
        sku_names=["s0", "s1"],
        dc_names=["D1", "D2"],
        stock=np.array([[1, 0], [0, 1]]),
        dc_capacity=np.array([10, 10]),
        ship_cost=np.zeros((2, 1)),
        fixed_ship_cost=0.0,
        transit_days=np.array([[1], [2]]),
        promise_days=np.array([3]),
        late_penalty_per_unit_day=1.0,
        unmet_penalty_per_unit=10.0,
        meta={},
    )
    instance = SimpleNamespace(fulfillment=fulfillment, n_orders=1)
    # line 0 -> D1 (1 day), line 1 -> D2 (2 days); slowest leg is 2 + handling.
    assert quote_promises(instance, "atp")[0] == 3


def test_atp_buffer_and_caps() -> None:
    fast = _instance([[1], [3]], [[1], [0]])
    assert quote_promises(fast, "atp_buffer")[0] == 3
    assert quote_promises(fast, "atp_cap2")[0] == 2
    assert quote_promises(fast, "atp_cap3")[0] == 2
    slow = _instance([[3], [3]], [[1], [0]])
    assert quote_promises(slow, "atp")[0] == 5
    assert quote_promises(slow, "atp_buffer")[0] == 5


def test_static_returns_input_promises() -> None:
    instance = _instance([[1], [3]], [[1], [0]])
    assert quote_promises(instance, "static").tolist() == [3]


def test_all_policies() -> None:
    instance = _instance([[1], [3]], [[1], [0]])
    assert quote_promises(instance, "all_2").tolist() == [2]
    assert quote_promises(instance, "all_3").tolist() == [3]
    assert quote_promises(instance, "all_5").tolist() == [5]


def test_frontier_aggregates_both_metrics() -> None:
    frame = pd.DataFrame(
        [
            {
                "cell": "static",
                "cell_label": "static",
                "avg_promise_days": 3.0,
                "fast_share": 0.3,
                "slow_share": 0.2,
                "quoted_otif_rate": 0.4,
                "static_sla_otif_rate": 0.4,
                "fill_rate": 0.8,
                "alloc_otif_rate": 0.5,
                "pick_otif_rate": 0.3,
            },
            {
                "cell": "static",
                "cell_label": "static",
                "avg_promise_days": 3.2,
                "fast_share": 0.2,
                "slow_share": 0.2,
                "quoted_otif_rate": 0.6,
                "static_sla_otif_rate": 0.3,
                "fill_rate": 0.8,
                "alloc_otif_rate": 0.5,
                "pick_otif_rate": 0.3,
            },
        ]
    )
    frontier = quote_frontier(frame)
    assert len(frontier) == 1
    row = frontier.iloc[0]
    assert abs(row["quoted_otif_rate"] - 0.5) < 1e-9
    assert abs(row["static_sla_otif_rate"] - 0.35) < 1e-9
    assert abs(row["avg_promise_days"] - 3.1) < 1e-9


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} quote tests passed")
