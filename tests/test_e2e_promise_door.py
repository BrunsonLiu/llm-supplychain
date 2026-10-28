"""Week-25 tests: promise-policy x dock-door interaction report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_promise_door_report,
    summarize_promise_door,
    write_promise_door_report,
)


def _frame() -> pd.DataFrame:
    rows = []
    for quote, offset in (("static", 0.0), ("atp", 0.1)):
        for door, util, blocked in ((0, 0.0, 0.0), (1, 0.40, 0.0), (2, 0.20, 0.0)):
            rows.append(
                {
                    "policy": "daily_1d",
                    "seed": 1,
                    "quote_policy": quote,
                    "door": door,
                    "e2e_otif_rate": 0.80 + offset,
                    "static_sla_otif_rate": 0.78 + offset,
                    "avg_promise_days": 3.1 if quote == "static" else 3.6,
                    "fast_share": 0.2,
                    "fill_rate": 0.96,
                    "late_orders": 20.0,
                    "backlog_units": 100,
                    "avg_delivery_day": 4.0,
                    "door_utilization": util,
                    "door_blocked": blocked,
                    "door_capacity_minutes": 480.0,
                }
            )
    return pd.DataFrame(rows)


def _payload():
    summary = summarize_promise_door(_frame())
    summary["label"] = summary["quote_policy"].map(
        {"static": "每日补货 · 固定 2/3/5", "atp": "每日补货 · ATP"}
    )
    summary["quote_label"] = summary["quote_policy"].map(
        {"static": "固定 2/3/5", "atp": "ATP"}
    )
    return {
        "dataset": {"orders": 80, "lines": 439, "units": 5418,
                    "week": "2011-11-28"},
        "settings": {"seeds": 3, "quote_policies": ["static", "atp"],
                     "doors": [0, 1, 2], "door_window_minutes": 480},
        "order_days": {"0": 13, "1": 12},
        "summary": summary.to_dict("records"),
        "rows": [],
        "limitations": ["门位是每日分钟预算"],
    }


def test_summarize_promise_door_groups() -> None:
    summary = summarize_promise_door(_frame())
    assert len(summary) == 6
    row = summary[
        (summary["quote_policy"] == "atp") & (summary["door"] == 1)
    ].iloc[0]
    assert abs(row["quoted_otif_mean"] - 0.90) < 1e-9
    assert abs(row["door_utilization"] - 0.40) < 1e-9


def test_report_mentions_door_and_service() -> None:
    text = build_promise_door_report(_payload())
    assert "门位利用" in text
    assert "0→1 door" in text
    assert "Promise and inventory still dominate the dock" in text
    assert "门位是每日分钟预算" in text


def test_write_promise_door_report(tmp_path: Path) -> None:
    paths = write_promise_door_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 25" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_promise_door_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 promise door tests passed")
