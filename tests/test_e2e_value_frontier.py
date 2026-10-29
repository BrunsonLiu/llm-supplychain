"""Week-29 tests: value-threshold frontier report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_value_frontier_report,
    summarize_value_frontier,
    write_value_frontier_report,
)


def _point(top, revenue, otif, all_otif):
    return {
        "policy": f"atp_3_top{top:g}" if top else "atp_3",
        "top_fraction": float(top),
        "top_label": f"Top {top:g}%" if top else "Top 0%",
        "value_label": "—" if not top else f"Top {top:g}% (≥1,000)",
        "orders": 400,
        "accepted_orders": 400 * revenue,
        "lost_orders": 400 * (1 - revenue),
        "accepted_rate": revenue,
        "accepted_units": 10000,
        "lost_units": 20000,
        "demand_revenue": 100000.0,
        "accepted_revenue": 100000.0 * revenue,
        "lost_revenue": 100000.0 * (1 - revenue),
        "revenue_accept_rate": revenue,
        "accepted_otif_mean": otif,
        "accepted_static_sla_mean": otif,
        "all_otif_mean": all_otif,
    }


def _payload():
    points = [
        _point(0, 0.52, 1.00, 0.70),
        _point(10, 0.78, 0.99, 0.76),
        _point(25, 0.88, 0.976, 0.815),
        _point(40, 0.95, 0.95, 0.90),
    ]
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 100000.0},
        "settings": {"seeds": 30, "tops": [5, 10, 15], "milp_time": 8,
                     "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": points,
        "rows": [],
        "limitations": ["所有阈值都是本次 400 单的样本内收入分位数"],
    }


def test_summarize_frontier_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10", "seed": 1, "orders": 2,
             "accepted_orders": 1, "lost_orders": 1, "accepted_rate": 0.5,
             "accepted_units": 10, "lost_units": 5, "demand_revenue": 100.0,
             "accepted_revenue": 70.0, "lost_revenue": 30.0,
             "revenue_accept_rate": 0.7, "accepted_otif_rate": 1.0,
             "accepted_static_sla_otif_rate": 1.0, "e2e_otif_rate": 0.5},
        ]
    )
    summary = summarize_value_frontier(frame)
    assert summary.iloc[0]["accepted_revenue"] == 70.0
    assert abs(summary.iloc[0]["revenue_accept_rate"] - 0.7) < 1e-9


def test_report_has_frontier_and_marginals() -> None:
    text = build_value_frontier_report(_payload())
    assert "价值门槛" in text
    assert "Accepted-OTIF frontier" in text
    assert "Best marginal trade-off" in text
    assert "All-order OTIF is a coverage check" in text
    assert "样本内收入分位数" in text


def test_write_frontier_report(tmp_path: Path) -> None:
    paths = write_value_frontier_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 29" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_frontier_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 value-frontier tests passed")
