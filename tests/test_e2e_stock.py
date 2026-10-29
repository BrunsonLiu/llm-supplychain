"""Week-36 tests: stock availability report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_stock_report,
    summarize_stock,
    write_stock_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all_85",
        "stock_factor": 0.85,
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
        "accepted_otif_mean": 0.948,
        "accepted_static_sla_mean": 0.842,
        "all_otif_mean": 0.948,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.85,
        "target_all_otif_mean": 0.85,
        "rest_accepted_otif_mean": 0.958,
        "accepted_fill_rate": 0.985,
        "accepted_backlog_units": 509.0,
        "departures": 73.0,
        "mean_wait_minutes": 220.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_all_85", "atp_all_100"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            _row(),
            _row(policy="atp_all_100", stock_factor=1.0,
                 accepted_otif_mean=0.985, all_otif_mean=0.985,
                 target_accepted_otif_mean=0.95, target_all_otif_mean=0.95,
                 rest_accepted_otif_mean=0.989,
                 accepted_fill_rate=0.995,
                 accepted_backlog_units=157.0, departures=69.0),
        ],
        "rows": [],
        "limitations": ["85%→100% 只改库存快照"],
    }


def test_summarize_stock_keeps_factor() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_all_100", "seed": 1, "orders": 2,
             "stock_factor": 1.0, "accepted_orders": 2, "lost_orders": 0,
             "accepted_rate": 1.0, "accepted_units": 10, "lost_units": 0,
             "demand_revenue": 100.0, "accepted_revenue": 100.0,
             "lost_revenue": 0.0, "revenue_accept_rate": 1.0,
             "accepted_otif_rate": 1.0, "accepted_static_sla_otif_rate": 0.9,
             "e2e_otif_rate": 1.0, "target_accepted_orders": 1,
             "target_accepted_otif_rate": 1.0, "target_all_otif_rate": 1.0,
             "rest_accepted_otif_rate": 1.0, "accepted_fill_rate": 1.0,
             "accepted_backlog_units": 0, "departures": 2,
             "mean_wait_minutes": 10.0},
        ]
    )
    summary = summarize_stock(frame)
    assert summary.iloc[0]["stock_factor"] == 1.0
    assert summary.iloc[0]["accepted_backlog_units"] == 0.0


def test_report_marks_stock_as_binding() -> None:
    text = build_stock_report(_payload())
    assert "Stock is the binding constraint" in text
    assert "85.0%" in text and "95.0%" in text
    assert "509" in text and "157" in text
    assert "85%→100%" in text


def test_write_stock_report(tmp_path: Path) -> None:
    paths = write_stock_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 36" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_stock_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 stock tests passed")
