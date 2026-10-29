"""Week-26 tests: same-day dispatch consolidation report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_consolidation_report,
    summarize_consolidation,
    write_consolidation_report,
)


def _frame() -> pd.DataFrame:
    specs = {
        ("static", 1, "immediate"): (0.857, 2.3, 65.0, 0.719, 14616),
        ("static", 1, "same6"): (0.868, 1.0, 62.7, 0.695, 14157),
        ("static", 1, "same12"): (0.868, 1.0, 60.7, 0.674, 13738),
        ("static", 2, "immediate"): (0.870, 0.0, 67.3, 0.371, 15120),
        ("static", 2, "same6"): (0.870, 0.0, 63.7, 0.353, 14379),
        ("static", 2, "same12"): (0.870, 0.0, 61.7, 0.342, 13960),
        ("atp", 1, "immediate"): (0.935, 4.0, 70.0, 0.770, 15730),
        ("atp", 1, "same6"): (0.950, 0.0, 64.5, 0.713, 14555),
        ("atp", 1, "same12"): (0.950, 0.0, 62.2, 0.689, 14073),
        ("atp", 2, "immediate"): (0.950, 0.0, 74.0, 0.406, 16616),
        ("atp", 2, "same6"): (0.950, 0.0, 64.5, 0.356, 14555),
        ("atp", 2, "same12"): (0.950, 0.0, 62.2, 0.345, 14073),
    }
    rows = []
    for (quote, door, mode), (otif, blocked, dep, util, cost) in specs.items():
        rows.append(
            {
                "policy": "daily_1d",
                "seed": 1,
                "quote_policy": quote,
                "door": door,
                "mode": mode,
                "e2e_otif_rate": otif,
                "static_sla_otif_rate": otif - 0.01,
                "fill_rate": 0.982 if quote == "static" else 0.977,
                "late_orders": (1 - otif) * 400,
                "backlog_units": 600,
                "departures": dep,
                "orders_per_departure": 3.1,
                "load_factor": 0.031,
                "door_utilization": util,
                "door_blocked": blocked,
                "roll_rate": 0.0,
                "mean_wait_minutes": 210.0 if mode == "immediate" else 254.0,
                "dispatch_cost": dep * 220.0,
                "holding_cost": 120.0,
                "dock_cost": cost,
            }
        )
    return pd.DataFrame(rows)


def _payload():
    summary = summarize_consolidation(_frame())
    summary["label"] = summary["quote_policy"].map(
        {"static": "每日补货 · 固定 2/3/5", "atp": "每日补货 · ATP"}
    )
    summary["mode_label"] = summary["mode"].map(
        {"immediate": "立即发车", "same6": "同日凑 6 单", "same12": "同日凑 12 单"}
    )
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28"},
        "settings": {"seeds": 30, "quote_policies": ["static", "atp"],
                     "doors": [1, 2],
                     "modes": ["immediate", "same6", "same12"],
                     "door_window_minutes": 480},
        "order_days": {"0": 66, "1": 73},
        "summary": summary.to_dict("records"),
        "rows": [],
        "limitations": ["只做同日集批：max_days=0、hold_day=0"],
    }


def test_summarize_consolidation_groups() -> None:
    summary = summarize_consolidation(_frame())
    assert len(summary) == 12
    row = summary[
        (summary["quote_policy"] == "atp")
        & (summary["door"] == 1)
        & (summary["mode"] == "same6")
    ].iloc[0]
    assert abs(row["quoted_otif_mean"] - 0.95) < 1e-9
    assert row["door_blocked_mean"] == 0.0
    assert row["roll_rate"] == 0.0


def test_report_has_service_cost_and_roll_scope() -> None:
    text = build_consolidation_report(_payload())
    assert "发车数" in text
    assert "blocked/日" in text
    assert "At one door" in text
    assert "roll_rate=0" in text
    assert "Do not compare `dock_cost`" in text
    assert "只做同日集批" in text


def test_write_consolidation_report(tmp_path: Path) -> None:
    paths = write_consolidation_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 26" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_consolidation_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 consolidation tests passed")
