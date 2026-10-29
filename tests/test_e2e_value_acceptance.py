"""Week-28 tests: value-tiered acceptance report and threshold validation."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_value_acceptance_report,
    prepare_flow,
    summarize_value_acceptance,
    write_value_acceptance_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_3",
        "label": "ATP 只接 ≤3 天",
        "quote_policy": "atp",
        "accept_cutoff": 3,
        "value_label": "—",
        "orders": 400,
        "accepted_orders": 285.0,
        "lost_orders": 115.0,
        "accepted_rate": 0.7125,
        "accepted_units": 14345,
        "lost_units": 18715,
        "demand_revenue": 170467.0,
        "accepted_revenue": 89441.0,
        "lost_revenue": 81026.0,
        "revenue_accept_rate": 0.5247,
        "accepted_otif_mean": 1.0,
        "accepted_static_sla_mean": 0.982,
        "quoted_otif_mean": 0.7125,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_3", "atp_3_top10"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": [
            _row(),
            _row(policy="atp_3_top10", label="ATP ≤3 天 + 收入 Top 10% 破例",
                 value_label="Top 10% (≥1,000)", accepted_orders=300.0,
                 lost_orders=100.0, accepted_rate=0.75,
                 accepted_revenue=120000.0, lost_revenue=50467.0,
                 revenue_accept_rate=0.704, accepted_otif_mean=0.92,
                 accepted_static_sla_mean=0.94, quoted_otif_mean=0.75),
        ],
        "rows": [],
        "limitations": ["价值阈值用本次 400 单的收入分位数"],
    }


def test_summarize_value_groups() -> None:
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
    summary = summarize_value_acceptance(frame)
    assert summary.iloc[0]["accepted_revenue"] == 70.0
    assert abs(summary.iloc[0]["revenue_accept_rate"] - 0.7) < 1e-9


def test_report_mentions_override_tradeoff() -> None:
    text = build_value_acceptance_report(_payload())
    assert "价值门槛" in text
    assert "Top 10%" in text
    assert "The override is a trade" in text
    assert "A value bar is not a profit bar" in text
    assert "in-sample quantile" in text


def test_write_value_report(tmp_path: Path) -> None:
    paths = write_value_acceptance_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 28" in paths["report"].read_text(encoding="utf-8")


def test_value_threshold_requires_aligned_order_value() -> None:
    fake = SimpleNamespace(n_orders=2)
    with pytest.raises(ValueError, match="order_value"):
        prepare_flow(
            fake,  # type: ignore[arg-type]
            pd.Series([0, 0]).to_numpy(),
            "daily_1d",
            accept_cutoff_days=3,
            accept_value_threshold=100.0,
        )
    with pytest.raises(ValueError, match="订单数"):
        prepare_flow(
            fake,  # type: ignore[arg-type]
            pd.Series([0, 0]).to_numpy(),
            "daily_1d",
            accept_cutoff_days=3,
            accept_value_threshold=100.0,
            order_value=pd.Series([1.0]).to_numpy(),
        )


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_value_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 value acceptance tests passed")
