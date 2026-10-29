"""Week-33 tests: high-value pick priority report and wave order."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_pick_priority_report,
    summarize_pick_priority,
    write_pick_priority_report,
)
from supply.network.warehouse import WarehouseLayout  # noqa: E402
from supply.wave import (  # noqa: E402
    ArrivalPlan,
    PromisePlan,
    build_wave_instance,
    simulate_online,
)


def _row(**overrides):
    base = {
        "policy": "atp_3_top10_edf",
        "label": "Top10 破例 · EDF 拣选",
        "target_label": "Top 10%",
        "orders": 400,
        "accepted_orders": 310.0,
        "lost_orders": 90.0,
        "accepted_rate": 0.775,
        "accepted_units": 15000,
        "lost_units": 18060,
        "demand_revenue": 170467.0,
        "accepted_revenue": 133445.0,
        "lost_revenue": 37022.0,
        "revenue_accept_rate": 0.7828,
        "accepted_otif_mean": 0.987,
        "accepted_static_sla_mean": 0.939,
        "all_otif_mean": 0.765,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.90,
        "target_all_otif_mean": 0.90,
        "rest_accepted_otif_mean": 1.0,
        "departures": 51.1,
        "mean_wait_minutes": 222.0,
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
            _row(policy="atp_3_top10_pick",
                 label="Top10 破例 · 高价值优先拣选",
                 mean_wait_minutes=218.0),
            _row(policy="atp_3_top25_edf", target_label="Top 25%"),
            _row(policy="atp_3_top25_pick", target_label="Top 25%",
                 label="Top25 破例 · 高价值优先拣选"),
        ],
        "rows": [],
        "limitations": ["拣选优先级只改下一个空闲拣货员先拿哪张已到票据"],
    }


def test_summarize_pick_priority_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10_pick", "seed": 1, "orders": 2,
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
    summary = summarize_pick_priority(frame)
    assert summary.iloc[0]["target_accepted_otif_mean"] == 1.0
    assert summary.iloc[0]["mean_wait_minutes"] == 10.0


def test_report_has_null_and_capacity_language() -> None:
    text = build_pick_priority_report(_payload())
    assert "same prepared flow" in text
    assert "did not move target OTIF" in text
    assert "still not extra capacity" in text
    assert "拣选优先级只改" in text


def test_write_pick_priority_report(tmp_path: Path) -> None:
    paths = write_pick_priority_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 33" in paths["report"].read_text(encoding="utf-8")


def test_priority_invoice_moves_to_first_wave() -> None:
    layout = WarehouseLayout(n_aisles=1, n_bays=2)
    assignment = {"S1": (1, 1, 0), "S2": (1, 2, 0)}
    lines = pd.DataFrame(
        [("A", "S1", 1), ("B", "S2", 1)],
        columns=["invoice", "sku", "quantity"],
    )
    instance = build_wave_instance(
        lines, assignment, layout, max_orders=2, max_lines=2
    )
    plan = PromisePlan(
        tier_of={"A": "standard", "B": "standard"},
        cutoff_of={"A": 100.0, "B": 300.0},
        tier_counts={},
        cutoffs={"standard": 300.0},
        mix={"standard": 1.0},
        seed=0,
    )
    arrivals = ArrivalPlan(
        arrival_of={"A": 0.0, "B": 0.0},
        tier_onsite={"standard": 1.0},
        tier_windows={"standard": 30.0},
        onsite={"standard": 2},
        seed=0,
    )
    plain = simulate_online(instance, plan, arrivals, policy="single")
    boosted = simulate_online(
        instance, plan, arrivals, policy="single", priority_invoices={"B"}
    )
    assert plain.jobs[0].invoices == ("A",)
    assert boosted.jobs[0].invoices == ("B",)


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_pick_priority_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 pick-priority tests passed")
