"""Week-27 tests: revenue-weighted order acceptance report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_revenue_acceptance_report,
    summarize_revenue_acceptance,
    write_revenue_acceptance_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all",
        "label": "每日补货 · ATP 接受全部",
        "quote_policy": "atp",
        "accept_cutoff": "全部",
        "orders": 400,
        "accepted_orders": 400.0,
        "lost_orders": 0.0,
        "accepted_rate": 1.0,
        "accepted_units": 33060,
        "lost_units": 0,
        "demand_revenue": 690000.0,
        "accepted_revenue": 690000.0,
        "lost_revenue": 0.0,
        "revenue_accept_rate": 1.0,
        "accepted_otif_mean": 0.95,
        "accepted_static_sla_mean": 0.837,
        "quoted_otif_mean": 0.95,
        "fill_mean": 0.983,
        "accepted_fill_mean": 0.983,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 690000.0},
        "settings": {"seeds": 30, "scenarios": ["static_all", "atp_all", "atp_3"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": [
            _row(policy="single_week_static", label="单周快照",
                 quote_policy="static", accepted_otif_mean=0.533,
                 accepted_static_sla_mean=0.533, quoted_otif_mean=0.533),
            _row(policy="static_all", label="每日补货 · 接受全部",
                 quote_policy="static", accepted_otif_mean=0.875,
                 accepted_static_sla_mean=0.875, quoted_otif_mean=0.875),
            _row(),
            _row(policy="atp_3", label="每日补货 · ATP 只接 ≤3 天",
                 accept_cutoff=3, accepted_orders=283.0, lost_orders=117.0,
                 accepted_rate=0.7075, accepted_units=18000,
                 lost_units=15060, accepted_revenue=350000.0,
                 lost_revenue=340000.0, revenue_accept_rate=0.507,
                 accepted_otif_mean=1.0, accepted_static_sla_mean=0.979,
                 quoted_otif_mean=0.7075, accepted_fill_mean=1.0),
            _row(policy="atp_2", label="每日补货 · ATP 只接 ≤2 天",
                 accept_cutoff=2, accepted_orders=0.0, lost_orders=400.0,
                 accepted_rate=0.0, accepted_units=0, lost_units=33060,
                 accepted_revenue=0.0, lost_revenue=690000.0,
                 revenue_accept_rate=0.0, accepted_otif_mean=0.0,
                 accepted_static_sla_mean=0.0, quoted_otif_mean=0.0,
                 accepted_fill_mean=0.0),
        ],
        "rows": [],
        "limitations": ["收入来自 Online Retail II 发票行"],
    }


def test_summarize_revenue_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3", "seed": 1, "orders": 2,
             "accepted_orders": 1, "lost_orders": 1, "accepted_rate": 0.5,
             "accepted_units": 10, "lost_units": 90, "demand_revenue": 100.0,
             "accepted_revenue": 20.0, "lost_revenue": 80.0,
             "revenue_accept_rate": 0.2, "accepted_otif_rate": 1.0,
             "accepted_static_sla_otif_rate": 1.0, "e2e_otif_rate": 0.5,
             "fill_rate": 0.8, "accepted_fill_rate": 1.0},
        ]
    )
    summary = summarize_revenue_acceptance(frame)
    row = summary.iloc[0]
    assert row["accepted_revenue"] == 20.0
    assert abs(row["revenue_accept_rate"] - 0.2) < 1e-9


def test_report_has_three_denominators() -> None:
    text = build_revenue_acceptance_report(_payload())
    assert "收入接单率" in text
    assert "订单接单率" in text
    assert "accepts nothing" in text
    assert "Revenue is not margin" in text
    assert "收入来自 Online Retail II" in text


def test_write_revenue_report(tmp_path: Path) -> None:
    paths = write_revenue_acceptance_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 27" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_revenue_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 revenue acceptance tests passed")
