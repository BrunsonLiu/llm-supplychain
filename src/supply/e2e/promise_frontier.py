"""Week 23: promise-service frontier across fixed and ATP quote policies."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

FRONTIER_QUOTE_POLICIES = (
    "static",
    "atp",
    "atp_buffer",
    "all_2",
    "all_3",
    "all_5",
)

QUOTE_LABELS = {
    "static": "固定 2/3/5",
    "atp": "ATP",
    "atp_buffer": "ATP+缓冲",
    "all_2": "全部 2 天",
    "all_3": "全部 3 天",
    "all_5": "全部 5 天",
}


def summarize_frontier(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per replenishment/quote policy, with the two service lenses."""
    rows: List[Dict[str, Any]] = []
    for (policy, quote), group in frame.groupby(
        ["policy", "quote_policy"], sort=False
    ):
        otif = group["e2e_otif_rate"].to_numpy(dtype=float)
        rows.append(
            {
                "policy": policy,
                "quote_policy": quote,
                "label": QUOTE_LABELS.get(quote, quote),
                "seeds": int(len(group)),
                "quoted_otif_mean": float(otif.mean()),
                "quoted_otif_p10": float(np.percentile(otif, 10)),
                "quoted_otif_p90": float(np.percentile(otif, 90)),
                "static_sla_otif_mean": float(
                    group["static_sla_otif_rate"].mean()
                ),
                "avg_promise_days": float(group["avg_promise_days"].mean()),
                "fast_share": float(group["fast_share"].mean()),
                "fill_mean": float(group["fill_rate"].mean()),
                "late_orders_mean": float(group["late_orders"].mean()),
                "backlog_units": int(group["backlog_units"].iloc[0]),
                "avg_delivery_day": float(group["avg_delivery_day"].mean()),
                "replenished_units": int(group["replenished_units"].iloc[0]),
            }
        )
    return pd.DataFrame(rows)


def _dominates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """True if left is at least as good on all four axes and better on one."""
    values = [
        ("quoted_otif_mean", 1.0),
        ("static_sla_otif_mean", 1.0),
        ("fill_mean", 1.0),
        ("avg_promise_days", -1.0),
    ]
    strictly_better = False
    for key, direction in values:
        left_value = float(left[key]) * direction
        right_value = float(right[key]) * direction
        if left_value < right_value - 1e-12:
            return False
        if left_value > right_value + 1e-12:
            strictly_better = True
    return strictly_better


def _two_way_dominates(
    left: Dict[str, Any], right: Dict[str, Any], y_key: str
) -> bool:
    """Shorter promise and at least as high service, with one strict win."""
    shorter = float(left["avg_promise_days"]) <= float(right["avg_promise_days"]) + 1e-12
    better = float(left[y_key]) >= float(right[y_key]) - 1e-12
    strict = (
        float(left["avg_promise_days"]) < float(right["avg_promise_days"]) - 1e-12
        or float(left[y_key]) > float(right[y_key]) + 1e-12
    )
    return shorter and better and strict


def annotate_two_way_frontier(
    summary: Sequence[Dict[str, Any]], y_key: str, prefix: str
) -> List[Dict[str, Any]]:
    """Mark rows on the (average promise ↓, y_key ↑) frontier."""
    records = [dict(row) for row in summary]
    for row in records:
        dominators = [
            other
            for other in records
            if other is not row and _two_way_dominates(other, row, y_key)
        ]
        row[f"{prefix}_pareto"] = not dominators
        row[f"{prefix}_dominated_by"] = (
            dominators[0]["quote_policy"] if dominators else ""
        )
    return records


def service_frontiers(summary: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Two customer-relevant frontiers, both with shorter promise as the x-axis.

    ``static_*`` uses the original fixed SLA as the service axis; this is the
    customer-outcome view. ``quoted_*`` uses the promise actually quoted; this
    is the view a service dashboard would show. Keeping them separate exposes
    policies that look good only because they re-wrote the promise.
    """
    records = [dict(row) for row in summary]
    records = annotate_two_way_frontier(
        records, "static_sla_otif_mean", "static"
    )
    records = annotate_two_way_frontier(
        records, "quoted_otif_mean", "quoted"
    )
    return records


def pareto_frontier(summary: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Annotate each row with ``pareto`` and ``dominated_by``.

    The frontier maximizes quoted OTIF, original-SLA OTIF and fill, and
    minimizes the average quoted promise. The baseline row (if present) is
    included as a reference, not as a policy that can be chosen daily.
    """
    records = [dict(row) for row in summary]
    for row in records:
        dominators = [
            other
            for other in records
            if other is not row and _dominates(other, row)
        ]
        row["pareto"] = not dominators
        row["dominated_by"] = (
            dominators[0]["quote_policy"] if dominators else ""
        )
    return records
