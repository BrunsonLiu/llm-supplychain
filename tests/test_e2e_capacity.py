"""Week-34 tests: one vs two pickers report and aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_capacity_report,
    summarize_capacity,
    write_capacity_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all_1p",
        "label": "ATP 接受全部 · 1 拣货员",
        "target_label": "Top 10%",
        "orders": 400,
        "pickers_per_dc": 1,
        "accepted_orders": 400.0,
        "lost_orders": 0.0,
        "accepted_rate": 1.0,
        "accepted_units": 33060,
        "lost_units": 0,
        "demand_revenue": 170467.0,
        "accepted_revenue": 170467.0,
        "lost_revenue": 0.0,
        "revenue_accept_rate": 1.0,
        "accepted_otif_mean": 0.938,
        "accepted_static_sla_mean": 0.808,
        "all_otif_mean": 0.938,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.80,
        "target_all_otif_mean": 0.80,
        "rest_accepted_otif_mean": 0.953,
        "departures": 77.0,
        "mean_wait_minutes": 220.0,
        "labor_minutes": 3160.0,
        "pick_makespan_minutes": 2208.0,
    }
    base.update(overrides)
    return base


def _payload():
    rows = [
        _row(),
        _row(policy="atp_all_2p", label="ATP 接受全部 · 2 拣货员",
             pickers_per_dc=2, labor_minutes=3363.0,
             pick_makespan_minutes=2202.0),
    ]
    for target, label, base_target in (("top10", "Top10", 0.925),
                                       ("top25", "Top25", 0.93)):
        for suffix, pickers, pick in (
            ("1p", 1, False), ("2p", 2, False), ("2p_pick", 2, True)
        ):
            rows.append(
                _row(
                    policy=f"atp_3_{target}_{suffix}",
                    label=f"{label} 破例 · {pickers} 拣货员"
                    + (" + 优先拣选" if pick else " EDF"),
                    target_label=f"Top {int(target[3:])}%",
                    pickers_per_dc=pickers,
                    accepted_orders=309.0,
                    accepted_rate=0.7725,
                    accepted_otif_mean=0.99,
                    target_accepted_otif_mean=base_target,
                    rest_accepted_otif_mean=1.0,
                    all_otif_mean=0.765,
                    labor_minutes=2266.0 if pickers == 1 else 2379.0,
                    pick_makespan_minutes=2024.0 if pickers == 1 else 2015.0,
                )
            )
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_all_1p"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": rows,
        "rows": [],
        "limitations": ["1/2 拣货员共用同一 prepared flow"],
    }


def test_summarize_capacity_keeps_pickers_and_labor() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_all_2p", "seed": 1, "orders": 2,
             "pickers_per_dc": 2, "accepted_orders": 2, "lost_orders": 0,
             "accepted_rate": 1.0, "accepted_units": 10, "lost_units": 0,
             "demand_revenue": 100.0, "accepted_revenue": 100.0,
             "lost_revenue": 0.0, "revenue_accept_rate": 1.0,
             "accepted_otif_rate": 1.0, "accepted_static_sla_otif_rate": 1.0,
             "e2e_otif_rate": 1.0, "target_accepted_orders": 1,
             "target_accepted_otif_rate": 1.0, "target_all_otif_rate": 1.0,
             "rest_accepted_otif_rate": 1.0, "departures": 2,
             "mean_wait_minutes": 10.0, "labor_minutes": 100.0,
             "pick_makespan_minutes": 50.0},
        ]
    )
    summary = summarize_capacity(frame)
    assert summary.iloc[0]["pickers"] == 2
    assert summary.iloc[0]["labor_minutes"] == 100.0


def test_report_says_first_picker_was_not_saturated() -> None:
    text = build_capacity_report(_payload())
    assert "same prepared flow" in text
    assert "not saturated" in text
    assert "600-min shift" in text
    assert "1/2 拣货员共用" in text


def test_write_capacity_report(tmp_path: Path) -> None:
    paths = write_capacity_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 34" in paths["report"].read_text(encoding="utf-8")


def test_capacity_report_marks_two_picker_null() -> None:
    text = build_capacity_report(_payload())
    assert "2-picker target/rest/all OTIF are identical" in text
    assert "Pick capacity is binding" not in text


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_capacity_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 capacity tests passed")
