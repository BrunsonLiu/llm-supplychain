"""Tests for the Week-17 dock-door extension of the dispatch model."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    DispatchCell,
    DispatchConfig,
    DispatchTicket,
    build_dock_report,
    dispatch_tickets,
)


def _ticket(
    name: str,
    *,
    dc: str = "London",
    lane: str = "UK",
    order: int = 0,
    pick_end: float = 100.0,
    deadline_day: int = 1,
    units: int = 1,
) -> DispatchTicket:
    return DispatchTicket(
        ticket=name,
        dc=dc,
        order=order,
        lane=lane,
        pick_end=pick_end,
        transit_days=1,
        promise_days=3,
        units=units,
        deadline_day=deadline_day,
    )


def _config(**overrides) -> DispatchConfig:
    base = dict(
        policy="immediate",
        departures=(300.0, 660.0),
        load_minutes=30.0,
        max_days=1,
        doors_per_dc=0,
        door_window_minutes=60.0,
        dock_load_minutes=60.0,
        dock_load_per_ticket=0.0,
    )
    base.update(overrides)
    return DispatchConfig(**base)


def test_door_config_validation() -> None:
    for kwargs in (
        {"doors_per_dc": -1},
        {"door_window_minutes": 0.0},
        {"dock_load_minutes": -1.0},
        {"dock_load_per_ticket": -1.0},
    ):
        try:
            _config(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def test_unlimited_doors_never_block() -> None:
    play = dispatch_tickets([_ticket("A"), _ticket("B", lane="FR", order=1)], _config())
    assert len(play.departures) == 2
    assert [row.day for row in play.departures] == [0, 0]
    assert play.door_blocked == 0
    assert play.door_minutes_used == 0.0


def test_one_door_defers_second_lane() -> None:
    play = dispatch_tickets(
        [_ticket("A"), _ticket("B", lane="FR", order=1)],
        _config(doors_per_dc=1),
    )
    assert [row.day for row in play.departures] == [0, 1]
    assert play.door_blocked == 2
    assert play.door_minutes_used == 120.0
    assert play.door_capacity_minutes == 120.0
    assert abs(play.door_minutes_used / play.door_capacity_minutes - 1.0) < 1e-9


def test_two_doors_load_both_lanes_together() -> None:
    play = dispatch_tickets(
        [_ticket("A"), _ticket("B", lane="FR", order=1)],
        _config(doors_per_dc=2),
    )
    assert len(play.departures) == 2
    assert [row.day for row in play.departures] == [0, 0]
    assert play.door_blocked == 0
    assert play.door_minutes_used == 120.0
    assert play.door_capacity_minutes == 120.0


def test_load_per_ticket_consumes_budget() -> None:
    play = dispatch_tickets(
        [_ticket("A", order=0), _ticket("B", order=1)],
        _config(doors_per_dc=1, door_window_minutes=100.0, dock_load_minutes=50.0,
                dock_load_per_ticket=30.0),
    )
    # 50 + 2 * 30 = 110 > 100, so the lane can never load.
    assert play.departures == []
    assert play.door_blocked == 4
    assert len(play.unshipped) == 2

    play = dispatch_tickets(
        [_ticket("A", order=0), _ticket("B", order=1)],
        _config(doors_per_dc=1, door_window_minutes=100.0, dock_load_minutes=50.0,
                dock_load_per_ticket=10.0),
    )
    assert len(play.departures) == 1
    assert play.door_minutes_used == 70.0


def test_door_budget_resets_next_day() -> None:
    records = [_ticket("A"), _ticket("B", lane="FR", order=1), _ticket("C", lane="DE", order=2)]
    play = dispatch_tickets(records, _config(doors_per_dc=1))
    assert [row.day for row in play.departures] == [0, 1]
    assert play.unshipped == ["C"]
    assert play.door_blocked >= 2


def test_cell_passes_door_settings_to_config() -> None:
    cell = DispatchCell(
        "x",
        "x",
        policy="immediate",
        doors_per_dc=2,
        door_window_minutes=480.0,
        dock_load_minutes=90.0,
        dock_load_per_ticket=1.0,
    )
    config = cell.config()
    assert config.doors_per_dc == 2
    assert config.door_window_minutes == 480.0
    assert config.dock_load_minutes == 90.0
    assert config.dock_load_per_ticket == 1.0
    assert cell.as_dict()["doors_per_dc"] == 2


def test_lane_summary_reflects_door_rolls() -> None:
    play = dispatch_tickets(
        [_ticket("A"), _ticket("B", lane="FR", order=1)],
        _config(doors_per_dc=1),
    )
    rolled = [row for row in play.tickets if row.ship_day >= 1]
    assert len(rolled) == 1
    assert rolled[0].lane == "FR"


def test_dock_report_sections() -> None:
    payload = {
        "dataset": {"orders": 1, "lines": 1, "units": 1, "week": "w"},
        "settings": {
            "pickers": 1,
            "shift_minutes": 600.0,
            "door_window": 600.0,
            "load_minutes_per_truck": 75.0,
            "load_minutes_per_ticket": 0.5,
            "dispatch_cost": 220.0,
            "holding_cost": 0.15,
        },
        "allocation": {
            "label": "x",
            "status": "FEASIBLE",
            "otif_rate": 0.5,
            "solve_seconds": 1.0,
        },
        "cells": [],
        "seeds": [1],
        "summary": [],
        "paired": [],
        "lanes": [],
        "limitations": ["声明值"],
    }
    text = build_dock_report(payload, generated="2026-01-01T00:00:00+00:00")
    for heading in (
        "# Dock doors",
        "## Assumptions",
        "## Cells",
        "## Service",
        "## Door capacity",
        "## Paired comparisons",
        "## Findings",
        "## Limitations",
    ):
        assert heading in text, heading
    assert "声明值" in text


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} dock tests passed")
