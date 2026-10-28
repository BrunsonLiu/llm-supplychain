# -*- coding: utf-8 -*-
"""Week-16 tests: outbound dispatch, carrier cutoffs and consolidation.

Run: python tests/test_e2e_dispatch.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from supply.e2e import (
    DEFAULT_CAPACITY,
    DEFAULT_DEPARTURES,
    ArrivalCurve,
    DispatchCell,
    DispatchConfig,
    DispatchTicket,
    E2EInstance,
    EmpiricalArrivals,
    PickPlan,
    TIER_CUTOFFS,
    build_dispatch_report,
    departure_slots,
    dispatch_tickets,
    lane_summary,
    paired_delta,
    pick_tickets,
    promise_deadline,
    run_dispatch_monte_carlo,
    simulate_dispatch,
    summarize_runs,
    ticket_records,
)
from supply.fulfillment import FulfillmentInstance, evaluate_allocation
from supply.network import WarehouseLayout

LAYOUT = WarehouseLayout(n_aisles=1, n_bays=4)
SLOTS = {"A": (1, 1, 0), "B": (1, 2, 0)}
ALL_ONSITE = {"express": 1.0, "standard": 1.0, "economy": 1.0}
NO_WINDOW = {"express": 0.0, "standard": 0.0, "economy": 0.0}


def _ticket(
    name: str,
    lane: str = "United Kingdom",
    dc: str = "North",
    pick_end: float = 100.0,
    deadline_day: int = 0,
    order: int = 0,
    transit: int = 2,
    promise: int = 2,
    units: int = 1,
) -> DispatchTicket:
    return DispatchTicket(
        ticket=name,
        dc=dc,
        order=order,
        lane=lane,
        pick_end=pick_end,
        transit_days=transit,
        promise_days=promise,
        units=units,
        deadline_day=deadline_day,
    )


def _fulfillment(transit=None, promises=(2, 3, 5)) -> FulfillmentInstance:
    if transit is None:
        transit = np.full((2, 3), 2, dtype=np.int64)
    return FulfillmentInstance(
        order_ids=["O0", "O1", "O2"],
        destinations=["United Kingdom", "Germany", "France"],
        line_order=np.array([0, 1, 1, 2]),
        line_sku=np.array([0, 0, 1, 1]),
        line_qty=np.array([10, 10, 10, 10]),
        sku_names=["A", "B"],
        dc_names=["North", "South"],
        stock=np.array([[20, 10], [10, 20]], dtype=np.int64),
        dc_capacity=np.array([50, 50], dtype=np.int64),
        ship_cost=np.ones((2, 3), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=transit,
        promise_days=np.array(promises, dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )


def _instance(transit=None, promises=(2, 3, 5)) -> E2EInstance:
    tier_of = {"O0": "express", "O1": "standard", "O2": "economy"}
    pick = PickPlan(
        tier_of=tier_of,
        cutoff_of={name: TIER_CUTOFFS[tier] for name, tier in tier_of.items()},
        arrival_of={"O0": 0.0, "O1": 0.0, "O2": 0.0},
        tier_onsite=dict(ALL_ONSITE),
        tier_windows=dict(NO_WINDOW),
        seed=1,
    )
    return E2EInstance(
        fulfillment=_fulfillment(transit, promises),
        layout=LAYOUT,
        slots=dict(SLOTS),
        pick=pick,
        pickers_per_dc=1,
    )


def _allocation(instance: E2EInstance):
    shipments = np.zeros((instance.fulfillment.n_lines, 2), dtype=np.int64)
    shipments[0, 0] = 10  # O0 -> North
    shipments[1, 0] = 10  # O1 -> North
    shipments[2, 1] = 10  # O1 -> South
    shipments[3, 1] = 10  # O2 -> South
    return evaluate_allocation(instance.fulfillment, shipments, name="manual")


def _fake_pick_result(instance, tickets, ends, otif_orders: int = 3):
    rows = []
    for group in tickets:
        end = float(ends.get(group.dc, 100.0))
        job = SimpleNamespace(invoices=list(group.order_index))
        rows.append(
            SimpleNamespace(
                dc=group.dc,
                schedule=SimpleNamespace(jobs=[job], ends=[end]),
            )
        )
    orders = instance.n_orders
    return SimpleNamespace(
        dc=rows,
        metrics={
            "e2e_otif_orders": float(otif_orders),
            "e2e_otif_rate": float(otif_orders) / orders if orders else 0.0,
            "pick_ok_orders": float(otif_orders),
        },
    )


def _curve() -> EmpiricalArrivals:
    curve = ArrivalCurve(shares=(0.1,) * 10, week="W1", label="test")
    return EmpiricalArrivals(
        curves=(curve,),
        mean=curve,
        target=curve,
        rows=(),
        skipped=(),
        diagnostics={},
    )


def test_departure_slots_and_cutoffs():
    config = DispatchConfig(departures=(300.0, 660.0), max_days=1)
    slots = departure_slots(config)
    assert len(slots) == 4
    assert slots[0] == (0, 300.0, 270.0)
    assert slots[1] == (0, 660.0, 630.0)
    assert slots[2] == (1, 300.0, 1710.0)
    assert slots[3] == (1, 660.0, 2070.0)
    assert DEFAULT_DEPARTURES == (300.0, 660.0)
    print("[OK] 发车时刻与装车截止按天展开")


def test_promise_deadline_clamps_to_horizon():
    assert promise_deadline(2, 2) == 0
    assert promise_deadline(3, 2) == 1
    assert promise_deadline(5, 2, max_days=3) == 3
    assert promise_deadline(2, 5) == 0
    assert promise_deadline(7, 1, max_days=4) == 4
    print("[OK] 承诺截止日 = 承诺天数 - 转运天数，并夹在发车窗口内")


def test_config_and_cell_validation():
    bad = [
        dict(policy="none"),
        dict(policy="unknown"),
        dict(departures=()),
        dict(departures=(660.0, 300.0)),
        dict(departures=(0.0, 300.0)),
        dict(load_minutes=-1.0),
        dict(min_load=0),
        dict(capacity=0),
        dict(max_days=-1),
        dict(dispatch_cost=-1.0),
        dict(hold_day=2, max_days=1),
    ]
    for case in bad:
        try:
            DispatchConfig(**case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法发车配置: {case}")
    for case in [dict(policy="bad"), dict(min_load=0), dict(capacity=0)]:
        try:
            DispatchCell("x", "x", **case)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法回放格: {case}")
    control = DispatchCell("pick", "pick", policy="none")
    assert control.config().policy == "promise"
    custom = DispatchCell(
        "x", "x", policy="hold", dispatch_cost=300.0, load_minutes=15.0
    )
    assert custom.config().dispatch_cost == 300.0
    assert custom.config().load_minutes == 15.0
    print("[OK] 发车配置与回放格拒绝非法参数")


def test_immediate_dispatches_at_first_feasible_departure():
    records = [
        _ticket("t0", pick_end=100.0, order=0),
        _ticket("t1", pick_end=200.0, order=1),
    ]
    play = dispatch_tickets(records, DispatchConfig(policy="immediate"))
    assert len(play.departures) == 1
    departure = play.departures[0]
    assert (departure.day, departure.minute) == (0, 300.0)
    assert departure.orders == 2
    assert [row.wait_minutes for row in play.tickets] == [200.0, 100.0]
    print("[OK] 即时策略在下一个可用发车时刻清空车道")


def test_hold_waits_for_min_load_or_end_of_day():
    records = [_ticket(f"t{i}", pick_end=100.0) for i in range(3)]
    config = DispatchConfig(policy="hold", min_load=6)
    play = dispatch_tickets(records, config)
    assert len(play.departures) == 1
    assert (play.departures[0].day, play.departures[0].minute) == (0, 660.0)

    config = DispatchConfig(policy="hold", min_load=2)
    play = dispatch_tickets(records, config)
    assert (play.departures[0].day, play.departures[0].minute) == (0, 300.0)
    print("[OK] 凑批策略达到最小批量即发，否则等日终发车")


def test_promise_holds_to_deadline_or_max_hold():
    record = _ticket("t0", pick_end=100.0, deadline_day=2)
    config = DispatchConfig(policy="promise", min_load=6, max_hold_minutes=0.0)
    play = dispatch_tickets([record], config)
    assert (play.departures[0].day, play.departures[0].minute) == (2, 660.0)

    config = DispatchConfig(policy="promise", min_load=6, max_hold_minutes=1440.0)
    play = dispatch_tickets([record], config)
    assert (play.departures[0].day, play.departures[0].minute) == (1, 300.0)

    urgent = _ticket("u0", pick_end=400.0, deadline_day=0)
    play = dispatch_tickets([urgent], config)
    assert (play.departures[0].day, play.departures[0].minute) == (0, 660.0)
    print("[OK] 承诺感知在截止日与最长等待之间取先到者")


def test_capacity_rolls_excess_to_next_departure():
    records = [_ticket(f"t{i}", pick_end=100.0, order=i) for i in range(5)]
    play = dispatch_tickets(
        records, DispatchConfig(policy="immediate", capacity=2, max_days=1)
    )
    loads = [(dep.day, dep.minute, dep.tickets) for dep in play.departures]
    assert loads == [(0, 300.0, 2), (0, 660.0, 2), (1, 300.0, 1)]
    assert not play.unshipped
    print("[OK] 超过车辆上限的票据滚到下一班发车")


def test_lanes_depart_separately():
    records = [
        _ticket("uk", lane="United Kingdom"),
        _ticket("de", lane="Germany"),
    ]
    play = dispatch_tickets(records, DispatchConfig(policy="immediate"))
    assert len(play.departures) == 2
    assert {dep.lane for dep in play.departures} == {"United Kingdom", "Germany"}
    print("[OK] 同一 DC 的不同目的国走不同车次")


def test_unshipped_when_horizon_runs_out():
    records = [_ticket("late", pick_end=700.0)]
    play = dispatch_tickets(
        records, DispatchConfig(policy="immediate", max_days=0)
    )
    assert not play.departures
    assert play.unshipped == ["late"]
    print("[OK] 超出最晚发车截止的票据保留为未发出")


def test_ticket_records_join_pick_times_and_promises():
    instance = _instance()
    allocation = _allocation(instance)
    tickets = pick_tickets(instance, allocation)
    pick_result = _fake_pick_result(instance, tickets, {"North": 100.0, "South": 200.0})
    records = ticket_records(instance, pick_result, tickets)

    assert len(records) == 4
    by_ticket = {record.ticket: record for record in records}
    assert by_ticket["O0@North"].lane == "United Kingdom"
    assert by_ticket["O0@North"].deadline_day == 0
    assert by_ticket["O1@North"].deadline_day == 1
    assert by_ticket["O1@South"].deadline_day == 1
    assert by_ticket["O2@South"].deadline_day == 3
    assert by_ticket["O0@North"].units == 10
    assert by_ticket["O2@South"].pick_end == 200.0
    print("[OK] 票据层把完工时间、车道、转运与承诺拼成发车记录")


def test_simulate_dispatch_scores_delivery_and_cost():
    instance = _instance()
    allocation = _allocation(instance)
    tickets = pick_tickets(instance, allocation)
    pick_result = _fake_pick_result(
        instance, tickets, {"North": 700.0, "South": 700.0}, otif_orders=3
    )
    outcome = simulate_dispatch(
        instance,
        allocation,
        pick_result,
        tickets,
        DispatchConfig(policy="immediate"),
    )
    metrics = outcome.metrics
    assert metrics["dock_otif_orders"] == 2  # O0 2-day promise misses; O1/O2 make it
    assert np.isclose(metrics["dock_otif_rate"], 2 / 3)
    assert metrics["unshipped_tickets"] == 0
    assert metrics["roll_tickets"] == 4
    assert metrics["departures"] == 4
    assert np.isclose(metrics["dispatch_cost"], 4 * 220.0)
    assert metrics["holding_cost"] > 0
    assert np.isclose(metrics["dock_cost"], metrics["dispatch_cost"] + metrics["holding_cost"])
    print("[OK] 发车后按最慢腿重新计算订单 OTIF 与月台成本")


def test_split_order_delivery_uses_slowest_leg():
    transit = np.array([[2, 2, 2], [3, 3, 3]], dtype=np.int64)
    instance = _instance(transit=transit)
    allocation = _allocation(instance)
    tickets = pick_tickets(instance, allocation)
    pick_result = _fake_pick_result(instance, tickets, {"North": 700.0, "South": 700.0})
    outcome = simulate_dispatch(
        instance, allocation, pick_result, tickets, DispatchConfig(policy="immediate")
    )
    # All tickets leave on day 1. O0: 1+2=3 > 2 fail. O1: North 1+2=3 ok,
    # South 1+3=4 > 3 fail, so the slow leg fails the order. O2: 1+3=4 <= 5 ok.
    assert outcome.metrics["dock_otif_orders"] == 1
    assert sorted(outcome.unshipped_orders) == []
    print("[OK] 拆单订单按最慢一条腿计算送达日")


def test_lane_summary_aggregates_departures():
    instance = _instance()
    allocation = _allocation(instance)
    tickets = pick_tickets(instance, allocation)
    pick_result = _fake_pick_result(instance, tickets, {"North": 700.0, "South": 700.0})
    outcome = simulate_dispatch(
        instance, allocation, pick_result, tickets, DispatchConfig(policy="immediate")
    )
    lanes = lane_summary(outcome)
    assert set(lanes["lane"]) == {"United Kingdom", "Germany", "France"}
    assert lanes["tickets"].sum() == 4
    assert lanes["departures"].sum() == 4
    print("[OK] 车道汇总保留车次、件数与滚存率")


def test_monte_carlo_is_reproducible_and_report_builds():
    instance = _instance()
    allocation = _allocation(instance)
    arrivals = _curve()
    cells = [
        DispatchCell("pick_control", "pick", policy="none"),
        DispatchCell("dock_two_immediate", "two", policy="immediate"),
        DispatchCell("dock_two_hold6", "hold", policy="hold", min_load=6),
    ]
    frame = run_dispatch_monte_carlo(
        instance, allocation, cells, [1, 2], arrivals, scenario="manual"
    )
    repeat = run_dispatch_monte_carlo(
        instance, allocation, cells, [1, 2], arrivals, scenario="manual"
    )
    assert frame.shape == repeat.shape
    assert np.allclose(
        frame["dock_otif_rate"].to_numpy(), repeat["dock_otif_rate"].to_numpy()
    )
    summary = summarize_runs(
        frame,
        metrics=["dock_otif_rate", "pick_otif_rate", "departures", "dispatch_cost"],
    )
    paired = paired_delta(frame, "pick_control", "dock_two_immediate", "dock_otif_rate")
    payload = {
        "dataset": {"orders": instance.n_orders, "lines": 4, "units": 40, "week": "W"},
        "settings": {"pickers": 1, "shift_minutes": 600, "milp_time": 1,
                     "dispatch_cost": 220, "holding_cost": 0.15, "max_hold_hours": 24},
        "allocation": {"label": "manual", "status": "FEASIBLE", "otif_rate": allocation.otif_rate},
        "cells": [cell.as_dict() for cell in cells],
        "seeds": [1, 2],
        "summary": summary.to_dict("records"),
        "paired": paired.to_dict("records"),
        "lanes": [],
        "limitations": ["x"],
    }
    markdown = build_dispatch_report(payload, generated="2020-01-01T00:00:00+00:00")
    for heading in ("## Assumptions", "## Service", "## Findings", "## Limitations"):
        assert heading in markdown
    assert "| Cell |" in markdown
    print("[OK] 蒙特卡洛可复现且报告包含全部章节")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("=" * 56)
    print("Week 16 outbound dispatch tests")
    print("=" * 56)
    tests = [
        test_departure_slots_and_cutoffs,
        test_promise_deadline_clamps_to_horizon,
        test_config_and_cell_validation,
        test_immediate_dispatches_at_first_feasible_departure,
        test_hold_waits_for_min_load_or_end_of_day,
        test_promise_holds_to_deadline_or_max_hold,
        test_capacity_rolls_excess_to_next_departure,
        test_lanes_depart_separately,
        test_unshipped_when_horizon_runs_out,
        test_ticket_records_join_pick_times_and_promises,
        test_simulate_dispatch_scores_delivery_and_cost,
        test_split_order_delivery_uses_slowest_leg,
        test_lane_summary_aggregates_departures,
        test_monte_carlo_is_reproducible_and_report_builds,
    ]
    for test in tests:
        test()
    print("=" * 56)
    print("All outbound dispatch tests passed")
    print("=" * 56)


if __name__ == "__main__":
    main()
