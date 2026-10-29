"""Week-30 tests: high-value promise-upgrade report and validation."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    build_service_upgrade_report,
    prepare_flow,
    summarize_service_upgrade,
    write_service_upgrade_report,
)


def _row(**overrides):
    base = {
        "policy": "atp_3_top10",
        "label": "ATP ≤3 天 + Top10 破例",
        "target_label": "Top 10%",
        "orders": 400,
        "accepted_orders": 309.0,
        "lost_orders": 91.0,
        "accepted_rate": 0.7725,
        "accepted_units": 15000,
        "lost_units": 18060,
        "demand_revenue": 170467.0,
        "accepted_revenue": 132873.0,
        "lost_revenue": 37594.0,
        "revenue_accept_rate": 0.7795,
        "accepted_otif_mean": 0.99,
        "accepted_static_sla_mean": 0.94,
        "all_otif_mean": 0.765,
        "target_accepted_orders": 40.0,
        "target_accepted_otif_mean": 0.95,
        "target_all_otif_mean": 0.95,
        "rest_accepted_otif_mean": 0.995,
    }
    base.update(overrides)
    return base


def _payload():
    return {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28", "demand_revenue": 170467.0},
        "settings": {"seeds": 30, "scenarios": ["atp_3_top10", "atp_3_top10_up3"],
                     "milp_time": 8, "revenue_coverage": 1.0},
        "order_days": {"0": 66, "1": 73},
        "summary": [
            _row(),
            _row(policy="atp_3_top10_up3",
                 label="ATP ≤3 天 + Top10 破例 + 承诺升到3天",
                 accepted_otif_mean=0.96, target_accepted_otif_mean=0.88,
                 target_all_otif_mean=0.88, rest_accepted_otif_mean=0.98,
                 all_otif_mean=0.74),
        ],
        "rows": [],
        "limitations": ["承诺升级是故意的过度承诺（over-promise）"],
    }


def test_summarize_upgrade_groups() -> None:
    frame = pd.DataFrame(
        [
            {"policy": "atp_3_top10_up3", "seed": 1, "orders": 2,
             "accepted_orders": 1, "lost_orders": 1, "accepted_rate": 0.5,
             "accepted_units": 10, "lost_units": 5, "demand_revenue": 100.0,
             "accepted_revenue": 70.0, "lost_revenue": 30.0,
             "revenue_accept_rate": 0.7, "accepted_otif_rate": 0.9,
             "accepted_static_sla_otif_rate": 0.8, "e2e_otif_rate": 0.5,
             "target_accepted_orders": 1, "target_accepted_otif_rate": 1.0,
             "target_all_otif_rate": 1.0, "rest_accepted_otif_rate": 0.0},
        ]
    )
    summary = summarize_service_upgrade(frame)
    assert summary.iloc[0]["target_accepted_otif_mean"] == 1.0
    assert abs(summary.iloc[0]["rest_accepted_otif_mean"]) < 1e-9


def test_report_has_target_rest_and_overpromise() -> None:
    text = build_service_upgrade_report(_payload())
    assert "目标接受 OTIF" in text
    assert "非目标接受 OTIF" in text
    assert "not a capacity reservation" in text
    assert "deliberate over-promising" in text
    assert "承诺升级是故意的过度承诺" in text


def test_write_upgrade_report(tmp_path: Path) -> None:
    paths = write_service_upgrade_report(_payload(), tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 30" in paths["report"].read_text(encoding="utf-8")


def test_upgrade_requires_target_days() -> None:
    fake = SimpleNamespace(n_orders=2)
    with pytest.raises(ValueError, match="承诺升级"):
        prepare_flow(
            fake,  # type: ignore[arg-type]
            pd.Series([0, 0]).to_numpy(),
            "daily_1d",
            accept_cutoff_days=3,
            upgrade_value_threshold=100.0,
            order_value=pd.Series([200.0, 10.0]).to_numpy(),
        )


if __name__ == "__main__":
    import tempfile

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            if name == "test_write_upgrade_report":
                with tempfile.TemporaryDirectory() as directory:
                    func(Path(directory))
            else:
                func()
            print(f"[OK] {name}")
    print("4 service-upgrade tests passed")
