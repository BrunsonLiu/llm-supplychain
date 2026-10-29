"""Week-38 tests: transit speed report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_transit_report,
    summarize_transit,
    write_transit_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all_100_cap2_t0",
        "stock_factor": 1.0,
        "dc_capacity_factor": 2.0,
        "transit_cut_days": 0,
        "orders": 400,
        "accepted_orders": 400.0,
        "lost_orders": 0.0,
        "accepted_rate": 1.0,
        "accepted_units": 33060,
        "lost_units": 0,
        "demand_revenue": 170467.0,
        "accepted_revenue": 170467.0,
        "lost_revenue": 0.0,
        "revenue_accept_rate": 1.0,
        "accepted_otif_mean": 0.985,
        "accepted_static_sla_mean": 0.87,
        "all_otif_mean": 0.985,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.925,
        "target_all_otif_mean": 0.925,
        "rest_accepted_otif_mean": 0.992,
        "accepted_fill_rate": 0.996,
        "accepted_backlog_units": 144.0,
        "avg_delivery_day": 4.52,
        "departures": 69.0,
        "mean_wait_minutes": 220.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30,
                     "scenarios": ["atp_all_100_cap2_t0", "atp_all_100_cap2_t1",
                                   "atp_all_100_cap2_t2"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            _row(),
            _row(policy="atp_all_100_cap2_t1", transit_cut_days=1,
                 accepted_otif_mean=0.99, all_otif_mean=0.99,
                 target_accepted_otif_mean=0.975, target_all_otif_mean=0.975,
                 avg_delivery_day=3.55),
            _row(policy="atp_all_100_cap2_t2", transit_cut_days=2,
                 accepted_otif_mean=0.992, all_otif_mean=0.992,
                 target_accepted_otif_mean=0.975, target_all_otif_mean=0.975,
                 rest_accepted_otif_mean=0.994, avg_delivery_day=3.28),
        ],
        "rows": [],
        "limitations": ["transit −1/−2 天只是承运商时效上界"],
    }


def test_summarize_transit_keeps_cut() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_all_100_cap2_t2", "seed": 1, "orders": 2,
             "stock_factor": 1.0, "dc_capacity_factor": 2.0,
             "transit_cut_days": 2, "accepted_orders": 2, "lost_orders": 0,
             "accepted_rate": 1.0, "accepted_units": 10, "lost_units": 0,
             "demand_revenue": 100.0, "accepted_revenue": 100.0,
             "lost_revenue": 0.0, "revenue_accept_rate": 1.0,
             "accepted_otif_rate": 1.0, "accepted_static_sla_otif_rate": 0.9,
             "e2e_otif_rate": 1.0, "target_accepted_orders": 1,
             "target_accepted_otif_rate": 1.0, "target_all_otif_rate": 1.0,
             "rest_accepted_otif_rate": 1.0, "accepted_fill_rate": 1.0,
             "accepted_backlog_units": 0, "avg_delivery_day": 3.0,
             "departures": 2, "mean_wait_minutes": 10.0},
        ]
    )
    summary = summarize_transit(frame)
    assert summary.iloc[0]["transit_cut_days"] == 2
    assert summary.iloc[0]["avg_delivery_day"] == 3.0


def test_report_marks_transit_as_real() -> None:
    text = build_transit_report(_payload())
    assert "Transit is a real part of the residual" in text
    assert "The speed-up saturates" in text
    assert "92.5%" in text and "97.5%" in text
    assert "4.52" in text and "3.55" in text


def test_write_transit_report(tmp_path: Path) -> None:
    paths = write_transit_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 38" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_transit_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 transit tests passed")
