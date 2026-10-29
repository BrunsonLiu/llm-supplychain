"""Week-31 tests: high-value allocation priority report and validation."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_value_priority_report,
    prepare_flow,
    summarize_value_priority,
    write_value_priority_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_3_top10_p1",
        "label": "Top10 破例 · 优先级 1×",
        "target_key": "top10",
        "target_label": "Top 10%",
        "priority_weight": 1.0,
        "orders": 400,
        "accepted_orders": 314.0,
        "lost_orders": 86.0,
        "accepted_rate": 0.785,
        "accepted_units": 15000,
        "lost_units": 18060,
        "demand_revenue": 170467.0,
        "accepted_revenue": 135330.0,
        "lost_revenue": 35137.0,
        "revenue_accept_rate": 0.7939,
        "accepted_otif_mean": 0.99,
        "accepted_static_sla_mean": 0.949,
        "all_otif_mean": 0.7775,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.925,
        "target_all_otif_mean": 0.925,
        "rest_accepted_otif_mean": 1.0,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_3_top10_p1"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": [
            _row(),
            _row(policy="atp_3_top10_p3", label="Top10 破例 · 优先级 3×",
                 priority_weight=3.0, target_accepted_otif_mean=0.98,
                 target_all_otif_mean=0.98, rest_accepted_otif_mean=0.97,
                 accepted_otif_mean=0.975, all_otif_mean=0.80),
        ],
        "rows": [],
        "limitations": ["优先级只改分单 MILP 的缺货/迟到权重"],
    }


def test_summarize_priority_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10_p3", "seed": 1, "orders": 2,
             "accepted_orders": 1, "lost_orders": 1, "accepted_rate": 0.5,
             "accepted_units": 10, "lost_units": 5, "demand_revenue": 100.0,
             "accepted_revenue": 70.0, "lost_revenue": 30.0,
             "revenue_accept_rate": 0.7, "accepted_otif_rate": 0.9,
             "accepted_static_sla_otif_rate": 0.8, "e2e_otif_rate": 0.5,
             "target_accepted_orders": 1, "target_accepted_otif_rate": 1.0,
             "target_all_otif_rate": 1.0, "rest_accepted_otif_rate": 0.0},
        ]
    )
    summary = summarize_value_priority(frame)
    assert summary.iloc[0]["target_accepted_otif_mean"] == 1.0
    assert abs(summary.iloc[0]["rest_accepted_otif_mean"]) < 1e-9


def test_report_has_redistribution_language() -> None:
    text = build_value_priority_report(_payload())
    assert "目标 OTIF" in text
    assert "非目标 OTIF" in text
    assert "redistribute, not create" in text
    assert "reserve stock" in text
    assert "优先级只改分单 MILP" in text


def test_write_priority_report(tmp_path: Path) -> None:
    paths = write_value_priority_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 31" in paths["report"].read_text(encoding="utf-8")


def test_priority_shape_validation() -> None:
    fake = SimpleNamespace(n_orders=2)
    with pytest.raises(ValueError, match="订单数一致"):
        prepare_flow(
            fake,  # type: ignore[arg-type]
            pd.Series([0, 0]).to_numpy(),
            "daily_1d",
            accept_cutoff_days=3,
            allocation_priority=pd.Series([1.0]).to_numpy(),
        )


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_priority_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 value-priority tests passed")
