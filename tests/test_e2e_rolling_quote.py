"""Week-22 tests: daily rolling replenishment with promise re-quoting."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e import (  # noqa: E402
    E2EInstance,
    PickPlan,
    TIER_CUTOFFS,
    build_rolling_quote_report,
    write_rolling_quote_report,
)
from supply.e2e.rolling_e2e import prepare_flow  # noqa: E402
from supply.fulfillment import FulfillmentInstance  # noqa: E402
from supply.network import WarehouseLayout  # noqa: E402


def _instance() -> E2EInstance:
    fulfillment = FulfillmentInstance(
        order_ids=["O0", "O1"],
        destinations=["United Kingdom", "Germany"],
        line_order=np.array([0, 1]),
        line_sku=np.array([0, 1]),
        line_qty=np.array([5, 5]),
        sku_names=["A", "B"],
        dc_names=["North", "South"],
        stock=np.array([[10, 0], [0, 10]], dtype=np.int64),
        dc_capacity=np.array([50, 50], dtype=np.int64),
        ship_cost=np.ones((2, 2), dtype=float),
        fixed_ship_cost=5.0,
        transit_days=np.full((2, 2), 2, dtype=np.int64),
        promise_days=np.array([2, 2], dtype=np.int64),
        late_penalty_per_unit_day=0.5,
        unmet_penalty_per_unit=6.0,
        meta={},
    )
    pick = PickPlan(
        tier_of={"O0": "express", "O1": "express"},
        cutoff_of={
            "O0": TIER_CUTOFFS["express"],
            "O1": TIER_CUTOFFS["express"],
        },
        arrival_of={"O0": 0.0, "O1": 0.0},
        tier_onsite={"express": 1.0, "standard": 1.0, "economy": 1.0},
        tier_windows={"express": 0.0, "standard": 0.0, "economy": 0.0},
        seed=1,
    )
    return E2EInstance(
        fulfillment=fulfillment,
        layout=WarehouseLayout(n_aisles=1, n_bays=4),
        slots={"A": (1, 1, 0), "B": (1, 2, 0)},
        pick=pick,
    )


def test_static_quote_preserves_base_promises() -> None:
    instance = _instance()
    flow = prepare_flow(
        instance,
        np.array([0, 1], dtype=np.int64),
        "none",
        milp_time=1.0,
        workers=1,
        quote_policy="static",
    )
    assert flow.promise_days.tolist() == [2, 2]


def test_atp_quote_produces_tiers() -> None:
    instance = _instance()
    flow = prepare_flow(
        instance,
        np.array([0, 1], dtype=np.int64),
        "none",
        milp_time=1.0,
        workers=1,
        quote_policy="atp",
    )
    assert set(flow.promise_days.tolist()).issubset({2, 3, 5})
    assert len(flow.promise_days) == 2


def test_report_contains_both_service_metrics() -> None:
    payload = {
        "dataset": {"orders": 400, "lines": 2477, "units": 33060,
                    "week": "2011-11-28"},
        "settings": {"seeds": 2, "policies": ["daily_1d"],
                     "quote_policies": ["static", "atp"], "milp_time": 8,
                     "stock_factor": 0.85},
        "order_days": {"0": 66, "1": 73, "2": 68, "3": 85, "4": 108},
        "summary": [
            {"policy": "daily_1d", "quote_policy": "static",
             "label": "每日 1 天", "seeds": 2, "quoted_otif_mean": 0.87,
             "quoted_otif_p10": 0.86, "quoted_otif_p90": 0.88,
             "static_sla_otif_mean": 0.87, "avg_promise_days": 3.1,
             "fast_share": 0.3, "fill_mean": 0.96, "late_orders_mean": 52,
             "backlog_units": 1258, "avg_delivery_day": 4.49},
            {"policy": "daily_1d", "quote_policy": "atp",
             "label": "每日 1 天", "seeds": 2, "quoted_otif_mean": 0.95,
             "quoted_otif_p10": 0.94, "quoted_otif_p90": 0.96,
             "static_sla_otif_mean": 0.84, "avg_promise_days": 4.7,
             "fast_share": 0.0, "fill_mean": 0.97, "late_orders_mean": 20,
             "backlog_units": 900, "avg_delivery_day": 4.8},
        ],
        "paired": [
            {"left": "daily_1d@atp", "right": "daily_1d@static", "n": 2,
             "mean": 0.08, "ci95": 0.0, "static_mean": -0.03,
             "win": 1.0, "loss": 0.0, "tie": 0.0}
        ],
        "by_day": [
            {"policy": "daily_1d", "label": "每日 1 天", "quote_policy": "static",
             "otif_day_0": 0.9},
        ],
        "limitations": ["ATP 不预留库存"],
    }
    text = build_rolling_quote_report(payload)
    assert "quoted OTIF" in text
    assert "原 SLA OTIF" in text
    assert "ATP 不预留库存" in text
    assert "+8.0 pp" in text


def test_write_report(tmp_path: Path) -> None:
    payload = {
        "dataset": {"orders": 1, "lines": 1, "units": 1, "week": "2011-11-28"},
        "settings": {"seeds": 1, "policies": [], "quote_policies": [],
                     "milp_time": 1, "stock_factor": 0.85},
        "order_days": {"0": 1},
        "summary": [],
        "paired": [],
        "by_day": [],
        "limitations": [],
    }
    paths = write_rolling_quote_report(payload, tmp_path)
    assert paths["report"].exists()
    assert paths["summary"].exists()
    assert "Week 22" in paths["report"].read_text(encoding="utf-8")


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
    print("4 rolling quote tests passed")
