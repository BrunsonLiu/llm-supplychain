"""Week-39 tests: local stock distribution report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_local_stock_report,
    summarize_local_stock,
    write_local_stock_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all_s100_cap2_t1",
        "stock_factor": 1.0,
        "dc_capacity_factor": 2.0,
        "transit_cut_days": 1,
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
        "accepted_static_sla_mean": 0.97,
        "all_otif_mean": 0.985,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.975,
        "target_all_otif_mean": 0.975,
        "rest_accepted_otif_mean": 0.986,
        "accepted_fill_rate": 0.996,
        "accepted_backlog_units": 138.0,
        "avg_delivery_day": 3.54,
        "departures": 69.5,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30,
                     "scenarios": ["atp_all_s100_cap2_t1",
                                   "atp_all_s120_cap2_t1",
                                   "atp_all_s150_cap2_t1"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            _row(),
            _row(policy="atp_all_s120_cap2_t1", stock_factor=1.2,
                 accepted_otif_mean=0.988, all_otif_mean=0.988,
                 target_accepted_otif_mean=0.95, target_all_otif_mean=0.95,
                 rest_accepted_otif_mean=0.992,
                 accepted_backlog_units=56.0, avg_delivery_day=3.46),
            _row(policy="atp_all_s150_cap2_t1", stock_factor=1.5,
                 accepted_otif_mean=0.997, all_otif_mean=0.997,
                 target_accepted_otif_mean=1.0, target_all_otif_mean=1.0,
                 rest_accepted_otif_mean=0.997,
                 accepted_backlog_units=4.0, avg_delivery_day=3.39),
        ],
        "rows": [],
        "limitations": ["120%/150% 只改初始库存快照"],
    }


def test_summarize_local_stock_keeps_factor() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_all_s150_cap2_t1", "seed": 1, "orders": 2,
             "stock_factor": 1.5, "dc_capacity_factor": 2.0,
             "transit_cut_days": 1, "accepted_orders": 2, "lost_orders": 0,
             "accepted_rate": 1.0, "accepted_units": 10, "lost_units": 0,
             "demand_revenue": 100.0, "accepted_revenue": 100.0,
             "lost_revenue": 0.0, "revenue_accept_rate": 1.0,
             "accepted_otif_rate": 1.0, "accepted_static_sla_otif_rate": 1.0,
             "e2e_otif_rate": 1.0, "target_accepted_orders": 1,
             "target_accepted_otif_rate": 1.0, "target_all_otif_rate": 1.0,
             "rest_accepted_otif_rate": 1.0, "accepted_fill_rate": 1.0,
             "accepted_backlog_units": 0, "avg_delivery_day": 3.0,
             "departures": 2, "mean_wait_minutes": 10.0},
        ]
    )
    summary = summarize_local_stock(frame)
    assert summary.iloc[0]["stock_factor"] == 1.5
    assert summary.iloc[0]["avg_delivery_day"] == 3.0


def test_report_marks_non_monotonic_overstock() -> None:
    text = build_local_stock_report(_payload())
    assert "Only the 150% overstock arm closes the residual" in text
    assert "not monotonic" in text
    assert "95.0%" in text and "100.0%" in text
    assert "1.5× demand" in text


def test_write_local_stock_report(tmp_path: Path) -> None:
    paths = write_local_stock_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 39" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_local_stock_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 local stock tests passed")
