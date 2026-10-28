"""Week-24 tests: order acceptance and the loss-aware report."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_order_acceptance_report,
    summarize_flow,
    write_order_acceptance_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_all",
        "label": "每日补货 · ATP 接受全部",
        "quote_policy": "atp",
        "accept_cutoff": "全部",
        "accepted_otif_mean": 0.75,
        "accepted_static_sla_mean": 0.55,
        "accepted_fill_mean": 0.963,
        "accepted_orders_mean": 80.0,
        "accepted_rate": 1.0,
        "accepted_backlog_units": 198,
        "lost_orders_mean": 0.0,
        "lost_units": 0,
        "accepted_avg_promise_days": 4.72,
        "e2e_otif_mean": 0.75,
        "orders_mean": 80.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 80, "lines": 439, "units": 5418,
                    "week": "2011-11-28"},
        "settings": {"seeds": 3, "scenarios": ["static_all", "atp_all", "atp_3"],
                     "milp_time": 2},
        "order_days": {"0": 13, "1": 12},
        "summary": [
            _row(policy="single_week_static", label="单周快照 · 固定承诺",
                 quote_policy="static", accepted_otif_mean=0.312,
                 accepted_static_sla_mean=0.312, accepted_fill_mean=0.728,
                 accepted_avg_promise_days=3.1, e2e_otif_mean=0.312),
            _row(policy="static_all", label="每日补货 · 接受全部",
                 quote_policy="static", accepted_otif_mean=0.562,
                 accepted_static_sla_mean=0.562, accepted_fill_mean=0.914,
                 accepted_avg_promise_days=3.1, e2e_otif_mean=0.562),
            _row(),
            _row(policy="atp_3", label="每日补货 · ATP 只接 ≤3 天",
                 accept_cutoff=3, accepted_otif_mean=1.0,
                 accepted_static_sla_mean=1.0, accepted_fill_mean=1.0,
                 accepted_orders_mean=16.0, accepted_rate=0.2,
                 accepted_backlog_units=0, lost_orders_mean=64.0,
                 lost_units=5088, accepted_avg_promise_days=3.0,
                 e2e_otif_mean=0.2),
            _row(policy="atp_2", label="每日补货 · ATP 只接 ≤2 天",
                 accept_cutoff=2, accepted_otif_mean=0.0,
                 accepted_static_sla_mean=0.0, accepted_fill_mean=0.0,
                 accepted_orders_mean=0.0, accepted_rate=0.0,
                 accepted_backlog_units=0, lost_orders_mean=80.0,
                 lost_units=5418, accepted_avg_promise_days=0.0,
                 e2e_otif_mean=0.0),
            _row(policy="static_3", label="每日补货 · 固定承诺只接 ≤3 天",
                 quote_policy="static", accept_cutoff=3,
                 accepted_otif_mean=0.547, accepted_static_sla_mean=0.547,
                 accepted_fill_mean=0.897, accepted_orders_mean=64.0,
                 accepted_rate=0.8, accepted_backlog_units=414,
                 lost_orders_mean=16.0, lost_units=1396,
                 accepted_avg_promise_days=2.62, e2e_otif_mean=0.438),
        ],
        "rows": [],
        "limitations": ["被拒订单按即期流失处理"],
    }


def test_report_exposes_loss_and_empty_denominator() -> None:
    text = build_order_acceptance_report(_payload())
    assert "接单率" in text
    assert "流失单位" in text
    assert "Cutoff 3 days with `atp`" in text
    assert "rejects every order" in text
    assert "被拒订单按即期流失处理" in text


def test_summarize_flow_acceptance_metrics() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "daily_1d", "seed": 1, "e2e_otif_rate": 0.5,
             "static_sla_otif_rate": 0.5, "accepted_otif_rate": 0.8,
             "accepted_static_sla_otif_rate": 0.7, "accepted_orders": 80,
             "lost_orders": 20, "accepted_units": 400, "lost_units": 100,
             "accepted_rate": 0.8, "accepted_fill_rate": 0.9,
             "accepted_backlog_units": 40, "accepted_late_orders": 16,
             "fill_rate": 0.8, "late_orders": 20, "backlog_units": 40,
             "avg_promise_days": 4.0, "accepted_avg_promise_days": 3.5,
             "fast_share": 0.0, "accepted_fast_share": 0.0,
             "avg_delivery_day": 4.0, "replenished_units": 50,
             "orders": 100},
        ]
    )
    summary = summarize_flow(frame)
    row = summary.iloc[0]
    assert abs(row["accepted_otif_mean"] - 0.8) < 1e-9
    assert row["accepted_orders_mean"] == 80
    assert row["lost_orders_mean"] == 20
    assert row["lost_units"] == 100


def test_write_report(tmp_path: Path) -> None:
    paths = write_order_acceptance_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 24" in paths["report"].read_text(encoding="utf-8")


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("3 order acceptance tests passed")
