"""Week-32 tests: high-value dispatch priority report and loading order."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_dispatch_priority_report,
    summarize_dispatch_priority,
    write_dispatch_priority_report,
)
from supply.e2e.dispatch import (  # noqa: E402
    DispatchConfig,
    DispatchTicket,
    dispatch_tickets,
)


def _row(**overrides):
    base = {
        "policy": "atp_3_top10_edf",
        "label": "Top10 破例 · EDF 发车",
        "target_label": "Top 10%",
        "orders": 400,
        "accepted_orders": 313.0,
        "lost_orders": 87.0,
        "accepted_rate": 0.7825,
        "accepted_units": 15000,
        "lost_units": 18060,
        "demand_revenue": 170467.0,
        "accepted_revenue": 134702.0,
        "lost_revenue": 35765.0,
        "revenue_accept_rate": 0.7902,
        "accepted_otif_mean": 0.99,
        "accepted_static_sla_mean": 0.936,
        "all_otif_mean": 0.775,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.925,
        "target_all_otif_mean": 0.925,
        "rest_accepted_otif_mean": 1.0,
        "departures": 20.0,
        "mean_wait_minutes": 120.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_3_top10_edf"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": [
            _row(),
            _row(policy="atp_3_top10_priority",
                 label="Top10 破例 · 高价值发车插队"),
            _row(policy="atp_3_top25_edf", target_label="Top 25%"),
            _row(policy="atp_3_top25_priority", target_label="Top 25%"),
        ],
        "rows": [],
        "limitations": ["发车插队只改同一车道内的装车顺序"],
    }


def test_summarize_dispatch_priority_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10_priority", "seed": 1, "orders": 2,
             "accepted_orders": 1, "lost_orders": 1, "accepted_rate": 0.5,
             "accepted_units": 10, "lost_units": 5, "demand_revenue": 100.0,
             "accepted_revenue": 70.0, "lost_revenue": 30.0,
             "revenue_accept_rate": 0.7, "accepted_otif_rate": 0.9,
             "accepted_static_sla_otif_rate": 0.8, "e2e_otif_rate": 0.5,
             "target_accepted_orders": 1, "target_accepted_otif_rate": 1.0,
             "target_all_otif_rate": 1.0, "rest_accepted_otif_rate": 0.0,
             "departures": 3, "mean_wait_minutes": 10.0},
        ]
    )
    summary = summarize_dispatch_priority(frame)
    assert summary.iloc[0]["target_accepted_otif_mean"] == 1.0
    assert summary.iloc[0]["departures"] == 3.0


def test_report_has_zero_sum_and_capacity_language() -> None:
    text = build_dispatch_priority_report(_payload())
    assert "目标 OTIF" in text
    assert "非目标 OTIF" in text
    assert "zero-sum" in text
    assert "no-op in this instance" in text
    assert "not extra capacity" in text
    assert "发车插队只改同一车道" in text


def test_write_dispatch_priority_report(tmp_path: Path) -> None:
    paths = write_dispatch_priority_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 32" in paths["report"].read_text(encoding="utf-8")


def test_dispatch_priority_reorders_within_lane() -> None:
    config = DispatchConfig(
        policy="immediate",
        departures=(300.0,),
        load_minutes=0.0,
        max_days=0,
        min_load=1,
        capacity=1,
        max_hold_minutes=0.0,
        doors_per_dc=0,
    )
    tickets = [
        DispatchTicket(
            ticket="low", dc="DC1", order=0, lane="FR", pick_end=0.0,
            transit_days=2, promise_days=2, units=1, deadline_day=0,
        ),
        DispatchTicket(
            ticket="high", dc="DC1", order=1, lane="FR", pick_end=0.0,
            transit_days=2, promise_days=3, units=1, deadline_day=1,
        ),
    ]
    plain = dispatch_tickets(tickets, config)
    boosted = dispatch_tickets(tickets, config, priority_orders=[1])
    assert plain.tickets[0].order == 0
    assert boosted.tickets[0].order == 1
    assert boosted.tickets[0].ticket == "high"


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_dispatch_priority_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 dispatch-priority tests passed")
