"""Replenishment policy definitions and static parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

import numpy as np

from .assumptions import safety_stock, service_level_z

POLICY_LABELS = {
    "eoq_rop": "(s, Q) 连续补货",
    "periodic": "(R, S) 周期补货",
    "min_max": "(s, S) 最小-最大",
}


@dataclass(frozen=True)
class PolicySpec:
    """One replenishment rule.

    ``eoq_rop`` orders a fixed EOQ when the inventory position drops below a
    reorder point. ``periodic`` reviews every ``review_period_weeks`` and orders
    up to a demand-cover target. ``min_max`` reviews continuously but orders up
    to an upper target instead of a fixed quantity.
    """

    kind: str
    service_level: float
    review_period_weeks: int = 2

    def validate(self) -> None:
        if self.kind not in POLICY_LABELS:
            raise ValueError(f"未知补货策略: {self.kind}")
        if not 0.5 <= self.service_level < 1.0:
            raise ValueError("service_level 必须在 [0.5, 1) 之间")
        if self.review_period_weeks < 1:
            raise ValueError("review_period_weeks 必须 >= 1")

    @property
    def label(self) -> str:
        return POLICY_LABELS[self.kind]


def policy_parameters(
    economics: Mapping[str, Any] | Any,
    policy: PolicySpec,
    lead_time_weeks: int,
) -> Dict[str, float]:
    """Static policy parameters evaluated at the mean demand level.

    The simulation uses the forecast path instead of the mean; these values are
    reported so a planner can inspect the resulting ROP / order-up-to levels.
    """
    policy.validate()
    mean = float(economics["mean_weekly"])
    sigma = float(economics["sigma_weekly"])
    lead = max(int(lead_time_weeks), 0)
    review = max(int(policy.review_period_weeks), 1)

    ss_lead = safety_stock(policy.service_level, sigma, lead)
    rop = mean * lead + ss_lead
    order_up_to = mean * (lead + review) + safety_stock(
        policy.service_level, sigma, lead + review
    )
    eoq = float(economics["eoq"])
    moq = float(economics["moq"])
    return {
        "z": float(service_level_z(policy.service_level)),
        "safety_stock": float(ss_lead),
        "reorder_point": float(rop),
        "order_up_to": float(order_up_to),
        "eoq": eoq,
        "order_quantity": float(max(eoq, moq)),
        "moq": moq,
        "lead_time_weeks": float(lead),
        "review_period_weeks": float(review),
    }


def default_policies(
    service_level: float,
    review_period_weeks: int = 2,
) -> list[PolicySpec]:
    return [
        PolicySpec("eoq_rop", service_level),
        PolicySpec("periodic", service_level, review_period_weeks),
        PolicySpec("min_max", service_level, review_period_weeks),
    ]
