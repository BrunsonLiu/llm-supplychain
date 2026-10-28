"""Multi-DC order fulfillment: instance builder, greedy baseline, CP-SAT MILP."""
from .instances import (
    DEFAULT_CAPACITY_SHARES,
    DEFAULT_STOCK_SHARES,
    FULFILLMENT_DCS,
    FulfillmentInstance,
    PROMISE_TIERS,
    build_fulfillment_instance,
)
from .report import build_fulfillment_report, write_fulfillment_report
from .solvers import (
    FulfillmentResult,
    allocate_greedy,
    allocate_milp,
    dc_table,
    evaluate_allocation,
    fulfillment_summary,
    order_table,
    promise_table,
)

__all__ = [
    "FULFILLMENT_DCS",
    "FulfillmentInstance",
    "build_fulfillment_instance",
    "DEFAULT_STOCK_SHARES",
    "DEFAULT_CAPACITY_SHARES",
    "PROMISE_TIERS",
    "FulfillmentResult",
    "allocate_greedy",
    "allocate_milp",
    "evaluate_allocation",
    "fulfillment_summary",
    "dc_table",
    "promise_table",
    "order_table",
    "build_fulfillment_report",
    "write_fulfillment_report",
]
