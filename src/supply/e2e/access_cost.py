"""Turn the stock-service frontier into a cost-ratio decision.

The end-to-end runs measure service at several fixed stock totals. This module
does not invent a demand distribution or an optimal inventory policy; it only
answers: for a declared weekly holding cost and stockout penalty, which tested
stock level is cheapest, and at what penalty/holding ratio does the answer
change?
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

DEFAULT_RATIOS: Sequence[float] = (0.0, 50.0, 75.0, 100.0, 200.0, 1_000.0, 2_000.0)


def baseline_frontier(rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, float]]:
    """Keep one baseline row per stock factor, sorted by stock."""
    grouped: Dict[float, Dict[str, float]] = {}
    for row in rows:
        if str(row.get("policy")) != "baseline":
            continue
        factor = float(row["stock_factor"])
        grouped[factor] = {
            "stock_factor": factor,
            "stock_units": float(row["stock_units"]),
            "target": float(row["target"]),
            "all": float(row["all"]),
            "backlog": float(row["backlog"]),
        }
    return [grouped[key] for key in sorted(grouped)]


def efficient_frontier(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, float]]:
    """Drop points with no more service and no less stock than another point."""
    points = [dict(row) for row in baseline_frontier(rows)]
    keep: List[Dict[str, float]] = []
    for point in points:
        dominated = False
        for other in points:
            if other is point:
                continue
            no_more_stock = other["stock_units"] <= point["stock_units"]
            no_less_target = other["target"] >= point["target"]
            no_less_all = other["all"] >= point["all"]
            no_more_backlog = other["backlog"] <= point["backlog"]
            strictly_better = (
                other["stock_units"] < point["stock_units"]
                or other["target"] > point["target"]
                or other["all"] > point["all"]
                or other["backlog"] < point["backlog"]
            )
            if (
                no_more_stock
                and no_less_target
                and no_less_all
                and no_more_backlog
                and strictly_better
            ):
                dominated = True
                break
        if not dominated:
            keep.append(point)
    return sorted(keep, key=lambda item: item["stock_units"])


def critical_ratios(
    rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, float]]:
    """Stockout/holding ratios where the cheapest adjacent step changes."""
    points = efficient_frontier(rows)
    result: List[Dict[str, float]] = []
    for before, after in zip(points, points[1:]):
        added = after["stock_units"] - before["stock_units"]
        cut = before["backlog"] - after["backlog"]
        result.append(
            {
                "from_stock": before["stock_factor"],
                "to_stock": after["stock_factor"],
                "added_units": added,
                "backlog_cut": cut,
                "break_even_ratio": added / cut if cut > 0 else float("inf"),
            }
        )
    return result


def choose_stock(
    rows: Sequence[Mapping[str, Any]],
    holding_cost: float,
    penalty_ratio: float,
) -> Dict[str, float]:
    """Cheapest tested point for ``penalty = ratio * holding_cost``."""
    if holding_cost <= 0:
        raise ValueError("holding_cost 必须为正")
    points = efficient_frontier(rows)
    if not points:
        raise ValueError("没有 baseline 前沿点")
    scored = []
    for point in points:
        cost = holding_cost * (
            point["stock_units"] + penalty_ratio * point["backlog"]
        )
        scored.append({**point, "cost": cost, "penalty_ratio": penalty_ratio})
    return min(scored, key=lambda item: (item["cost"], item["stock_units"]))


def cost_table(
    rows: Sequence[Mapping[str, Any]],
    ratios: Sequence[float] = DEFAULT_RATIOS,
    holding_cost: float = 0.10,
) -> List[Dict[str, float]]:
    return [
        choose_stock(rows, holding_cost=holding_cost, penalty_ratio=float(ratio))
        for ratio in ratios
    ]


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def build_stock_cost_report(
    rows: Sequence[Mapping[str, Any]],
    holding_cost: float = 0.10,
    ratios: Sequence[float] = DEFAULT_RATIOS,
    week: int = 46,
) -> str:
    points = efficient_frontier(rows)
    critical = critical_ratios(rows)
    table = cost_table(rows, ratios=ratios, holding_cost=holding_cost)
    tested = baseline_frontier(rows)
    stock_list = "/".join(f"{point['stock_factor']:.0%}" for point in tested)
    lines = [
        f"# Week {week}: stock-service cost decision",
        "",
        f"The measured {stock_list} stock frontier is turned into a decision "
        "with one declared weekly holding cost and a stockout penalty "
        "expressed as a multiple of that holding cost. This is a post-hoc "
        "decision layer, not a new demand or inventory model.",
        "",
        f"Weekly holding cost: **€{holding_cost:.2f}/unit-week**. "
        "Total cost = holding cost × stock units + stockout penalty × backlog "
        "units. The stockout penalty is `ratio × holding cost`.",
        "",
        "## Efficient frontier",
        "",
        "| stock | units | target | all | backlog |",
        "|---:|---:|---:|---:|---:|",
    ]
    for point in points:
        lines.append(
            f"| {point['stock_factor']:.0%} | {_num(point['stock_units'])} | "
            f"{_pct(point['target'])} | {_pct(point['all'])} | "
            f"{_num(point['backlog'], 1)} |"
        )
    lines += [
        "",
        "## Cheapest tested stock level by penalty/holding ratio",
        "",
        "| penalty/holding | chosen stock | units | target | all | backlog | cost |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in table:
        lines.append(
            f"| {item['penalty_ratio']:.0f} | {item['stock_factor']:.0%} | "
            f"{_num(item['stock_units'])} | {_pct(item['target'])} | "
            f"{_pct(item['all'])} | {_num(item['backlog'], 1)} | "
            f"€{_num(item['cost'], 2)} |"
        )
    lines += [
        "",
        "## Break-even ratios",
        "",
        "A step is worth taking when the stockout penalty per backlog unit is "
        "above `added stock / backlog cut` times the holding cost:",
        "",
        "| step | added units | backlog cut | break-even penalty/holding |",
        "|---|---:|---:|---:|",
    ]
    for item in critical:
        ratio = item["break_even_ratio"]
        ratio_text = "∞ (no backlog cut)" if ratio == float("inf") else f"{ratio:,.1f}"
        lines.append(
            f"| {item['from_stock']:.0%} → {item['to_stock']:.0%} | "
            f"+{_num(item['added_units'])} | {_num(item['backlog_cut'], 1)} | "
            f"**{ratio_text}** |"
        )
    lines += [
        "",
        "## Reading",
        "",
        "- The answer is **not a universal stock level**. The cheapest tested "
        "point moves right as the stockout penalty rises, and the break-even "
        "ratios below are the decision boundaries. A tested point is dropped "
        "when another point has no more stock and no worse service; on the "
        "full Week45 grid this removed 150% in favour of 140%.",
        "- The break-even numbers are the useful output: they translate the "
        "service frontier into a cost-penalty condition instead of an "
        "arbitrary `hold more` recommendation.",
        "- Holding cost is applied to the whole week's stock and backlog is a "
        "proxy for shortage; there is no lost-sales, goodwill, markdown, "
        "working-capital or lead-time cost. Cost levels are illustrative, "
        "not accounting numbers.",
        "- One target week, one layout/shift, 30 seeds × 3 repeats, fixed "
        "demand; this is a post-hoc read of the stock frontier in the same "
        "report, not a multi-week inventory policy.",
    ]
    return "\n".join(lines) + "\n"
