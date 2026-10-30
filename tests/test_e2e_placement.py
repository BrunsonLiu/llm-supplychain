"""Week-40 tests: fixed-total stock placement report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_placement_report,
    summarize_placement,
    write_placement_report,
)


def _row(placement: str, target: float, backlog: float, seed: int = 1):
    return {
        "placement": placement,
        "label": placement,
        "shares": "34/28/38" if placement == "baseline" else "33/33/34",
        "orders": 400,
        "stock_units": 33060,
        "accepted_orders": 400.0,
        "accepted_rate": 1.0,
        "accepted_otif_rate": 0.985,
        "e2e_otif_rate": 0.985,
        "target_accepted_otif_rate": target,
        "rest_accepted_otif_rate": 0.986,
        "accepted_fill_rate": 0.996,
        "accepted_backlog_units": backlog,
        "avg_delivery_day": 3.54,
        "departures": 70.0,
        "seed": seed,
    }


def _payload():
    return {
        "dataset": {
            "orders": 400,
            "lines": 2477,
            "units": 33060,
            "week": "2011-11-28",
        },
        "settings": {
            "seeds": 30,
            "placements": ["baseline", "balanced"],
            "milp_time": 8,
            "solver_noise_pp": 5.0,
            "baseline_repeats": [92.5, 95.0, 97.5],
        },
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            {
                "placement": "baseline",
                "label": "基线 34/28/38",
                "shares": "34/28/38",
                "stock_units": 33060,
                "accepted_orders": 400.0,
                "accepted_otif_mean": 0.985,
                "target_accepted_otif_mean": 0.95,
                "rest_accepted_otif_mean": 0.986,
                "all_otif_mean": 0.985,
                "accepted_fill_rate": 0.996,
                "accepted_backlog_units": 138.0,
                "avg_delivery_day": 3.54,
            },
            {
                "placement": "balanced",
                "label": "均衡 33/33/34",
                "shares": "33/33/34",
                "stock_units": 33060,
                "accepted_orders": 400.0,
                "accepted_otif_mean": 0.988,
                "target_accepted_otif_mean": 0.975,
                "rest_accepted_otif_mean": 0.989,
                "all_otif_mean": 0.988,
                "accepted_fill_rate": 0.997,
                "accepted_backlog_units": 96.0,
                "avg_delivery_day": 3.5,
            },
        ],
        "rows": [],
        "limitations": ["固定总量，只改 DC 占比"],
    }


def test_summarize_placement_averages_seeds() -> None:
    frame = pd.DataFrame(
        [
            _row("baseline", 0.97, 140.0, seed=1),
            _row("baseline", 0.98, 136.0, seed=2),
        ]
    )
    summary = summarize_placement(frame)
    row = summary.iloc[0]
    assert row["placement"] == "baseline"
    assert abs(row["target_accepted_otif_mean"] - 0.975) < 1e-9
    assert abs(row["accepted_backlog_units"] - 138.0) < 1e-9
    print("[OK] placement 汇总按 seed 取均值")


def test_report_flags_not_robust() -> None:
    text = build_placement_report(_payload())
    assert "Best fixed-total rebalance" in text
    assert "33/33/34" in text
    assert "95.0%" in text and "97.5%" in text
    assert "Directional, but not robust" in text
    assert "Baseline repeats matter" in text
    print("[OK] 报告把 2.5pp 判为方向性但不稳健")


def test_baseline_only_does_not_crash() -> None:
    payload = _payload()
    payload["summary"] = payload["summary"][:1]
    text = build_placement_report(payload)
    assert "Only the baseline was selected" in text
    print("[OK] 只跑 baseline 时报告不崩溃")


def test_write_placement_report(tmp_path: Path) -> None:
    paths = write_placement_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 40" in paths["report"].read_text(encoding="utf-8")
    print("[OK] 报告与 JSON 落盘")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_placement_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 placement tests passed")
