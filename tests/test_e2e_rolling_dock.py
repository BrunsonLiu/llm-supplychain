"""Week-21 tests: rolling end-to-end with dock door capacity."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    DispatchCell,
    build_rolling_dock_report,
    write_rolling_dock_report,
)


def test_dispatch_cell_exposes_door_config() -> None:
    cell = DispatchCell(
        key="door1", label="door1", policy="immediate", doors_per_dc=1
    )
    config = cell.config()
    assert config.doors_per_dc == 1
    assert config.door_window_minutes > 0
    assert cell.as_dict()["doors_per_dc"] == 1


def test_report_handles_door_effect_payload() -> None:
    summary = []
    for policy, label, doors, otif in [
        ("single_week", "单周", 0, 0.51),
        ("single_week", "单周", 1, 0.46),
        ("daily_1d", "每日1天", 0, 0.87),
        ("daily_1d", "每日1天", 1, 0.82),
    ]:
        summary.append(
            {
                "policy": policy,
                "label": label,
                "doors": doors,
                "seeds": 2,
                "e2e_otif_mean": otif,
                "e2e_otif_p10": otif - 0.01,
                "e2e_otif_p90": otif + 0.01,
                "fill_mean": 0.9,
                "late_orders_mean": 20.0,
                "backlog_units": 100,
                "avg_delivery_day": 3.0,
                "door_utilization": 0.95 if doors else 0.0,
                "door_blocked_mean": 3.0 if doors else 0.0,
            }
        )
    payload = {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28"},
        "settings": {"seeds": 2, "doors": [0, 1], "milp_time": 8,
                     "baseline_milp_time": 60, "stock_factor": 0.85},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": summary,
        "paired": [
            {"left": "daily_1d@1门", "right": "daily_1d@0门", "n": 2,
             "mean": -0.05, "ci95": 0.0, "win": 0.0, "loss": 1.0,
             "tie": 0.0}
        ],
        "by_day": [
            {"policy": "daily_1d", "label": "每日1天", "doors": 0,
             "otif_day_0": 0.9, "otif_day_4": 0.7},
        ],
        "limitations": ["门位是分钟预算"],
    }
    text = build_rolling_dock_report(payload)
    assert "门位/DC" in text
    assert "每日1天" in text
    assert "门位是分钟预算" in text
    assert "-5.0 pp" in text


def test_write_rolling_dock_report(tmp_path: Path) -> None:
    payload = {
        "dataset": {"orders": 1, "lines": 1, "units": 1, "week": "2011-11-28"},
        "settings": {"seeds": 1, "doors": [0], "milp_time": 1,
                     "baseline_milp_time": 1, "stock_factor": 0.85},
        "order_days": {"0": 1},
        "summary": [],
        "paired": [],
        "by_day": [],
        "limitations": [],
    }
    paths = write_rolling_dock_report(payload, tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 21" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_rolling_dock_report":
                import tempfile

                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 rolling dock tests passed")
