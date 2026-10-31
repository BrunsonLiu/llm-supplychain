"""Turn the stock-service frontier into a cost-ratio decision.

The end-to-end runs measure service at several fixed stock totals. This module
does not invent a demand distribution or an optimal inventory policy; it only
answers: for a declared weekly holding cost and stockout penalty, which tested
stock level is cheapest, and at what penalty/holding ratio does the answer
change?
"""
from __future__ import annotations

from collections import Counter
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


def seed_cost_choices(
    payloads: Sequence[tuple[float, Mapping[str, Any]]],
    ratios: Sequence[float] = DEFAULT_RATIOS,
    holding_cost: float = 0.10,
) -> List[Dict[str, Any]]:
    """Cheapest factor for each repeat/seed, using each factor's raw rows."""
    factors = sorted(float(factor) for factor, _ in payloads)
    by_key: Dict[tuple[int, int], Dict[float, Mapping[str, Any]]] = {}
    for factor, payload in payloads:
        factor = float(factor)
        for row in payload.get("rows", []):
            if str(row.get("policy")) != "baseline":
                continue
            key = (int(row["repeat"]), int(row["seed"]))
            by_key.setdefault(key, {})[factor] = row
    complete = {
        key: rows
        for key, rows in by_key.items()
        if all(factor in rows for factor in factors)
    }
    result: List[Dict[str, Any]] = []
    for ratio in ratios:
        choices: List[float] = []
        for rows in complete.values():
            scored = []
            for factor in factors:
                row = rows[factor]
                cost = holding_cost * (
                    float(row["stock_units"]) + ratio * float(row["accepted_backlog_units"])
                )
                scored.append((cost, factor))
            choices.append(min(scored)[1])
        counts = Counter(choices)
        n = len(choices)
        modal = max(counts, key=lambda factor: (counts[factor], -factor))
        result.append(
            {
                "ratio": float(ratio),
                "n": n,
                "counts": {f"{factor:.2f}": count for factor, count in sorted(counts.items())},
                "shares": {
                    f"{factor:.2f}": count / n for factor, count in sorted(counts.items())
                },
                "modal": modal,
                "mean_factor": sum(choices) / n if n else 0.0,
                "unanimous": n > 0 and len(counts) == 1,
            }
        )
    return result


def aggregate_rows(
    payloads: Sequence[tuple[float, Mapping[str, Any]]],
) -> List[Dict[str, float]]:
    """One baseline mean row per factor, for a mean-based cost comparison."""
    rows: List[Dict[str, float]] = []
    for factor, payload in sorted(payloads, key=lambda item: float(item[0])):
        baseline = next(
            (row for row in payload.get("summary", []) if row.get("policy") == "baseline"),
            None,
        )
        if baseline is None:
            continue
        rows.append(
            {
                "policy": "baseline",
                "stock_factor": float(factor),
                "stock_units": float(payload["settings"]["stock_units"]),
                "target": float(baseline["target_accepted_otif_mean"]),
                "all": float(baseline["accepted_otif_mean"]),
                "backlog": float(baseline["accepted_backlog_units"]),
            }
        )
    return rows


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.1f}%"


def _num(value: float, digits: int = 0) -> str:
    return f"{float(value):,.{digits}f}"


def _distribution_text(item: Mapping[str, Any], factors: Sequence[float]) -> str:
    parts = []
    for factor in factors:
        share = item["shares"].get(f"{factor:.2f}", 0.0)
        if share > 0:
            parts.append(f"{factor:.0%}:{share:.0%}")
    return " / ".join(parts) if parts else "—"


def build_seed_cost_report(
    insample_payloads: Sequence[tuple[float, Mapping[str, Any]]],
    oos_payloads: Sequence[tuple[float, Mapping[str, Any]]],
    holding_cost: float = 0.10,
    ratios: Sequence[float] = DEFAULT_RATIOS,
    week: int = 48,
) -> str:
    in_factors = sorted(float(factor) for factor, _ in insample_payloads)
    oos_factors = sorted(float(factor) for factor, _ in oos_payloads)
    in_choices = seed_cost_choices(
        insample_payloads, ratios=ratios, holding_cost=holding_cost
    )
    oos_choices = seed_cost_choices(
        oos_payloads, ratios=ratios, holding_cost=holding_cost
    )
    in_mean = {
        ratio: choose_stock(
            aggregate_rows(insample_payloads),
            holding_cost=holding_cost,
            penalty_ratio=float(ratio),
        )["stock_factor"]
        for ratio in ratios
    }
    oos_mean = {
        ratio: choose_stock(
            aggregate_rows(oos_payloads),
            holding_cost=holding_cost,
            penalty_ratio=float(ratio),
        )["stock_factor"]
        for ratio in ratios
    }
    lines = [
        f"# Week {week}: seed-level stock-cost stability",
        "",
        "The cost decision in Weeks 46-47 uses one mean frontier. This layer "
        "recomputes the cheapest tested stock level for every `(repeat, seed)` "
        "cell, so the decision is reported as a distribution rather than a "
        "single point. It reuses the existing runs; no new simulation.",
        "",
        f"Weekly holding cost: **€{holding_cost:.2f}/unit-week**; stockout "
        "penalty = `ratio × holding cost`; 90 repeat/seed cells per dataset.",
        "",
        "## In-sample Week45 (100%/125%/135%/140%/150%)",
        "",
        f"| penalty/holding | n | seed choices | modal | mean factor | mean-data choice |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for item in in_choices:
        ratio = item["ratio"]
        lines.append(
            f"| {ratio:.0f} | {item['n']} | "
            f"{_distribution_text(item, in_factors)} | "
            f"{item['modal']:.0%} | {item['mean_factor']:.2%} | "
            f"{in_mean[ratio]:.0%} |"
        )
    lines += [
        "",
        "## Out-of-sample Week47 (100%/125%/140%)",
        "",
        f"| penalty/holding | n | seed choices | modal | mean factor | mean-data choice |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for item in oos_choices:
        ratio = item["ratio"]
        lines.append(
            f"| {ratio:.0f} | {item['n']} | "
            f"{_distribution_text(item, oos_factors)} | "
            f"{item['modal']:.0%} | {item['mean_factor']:.2%} | "
            f"{oos_mean[ratio]:.0%} |"
        )
    lines += [
        "",
        "## Findings",
        "",
    ]
    for label, choices, factors in (
        ("in-sample", in_choices, in_factors),
        ("out-of-sample", oos_choices, oos_factors),
    ):
        item = next((row for row in choices if row["ratio"] == 100.0), None)
        if item is not None:
            dist = _distribution_text(item, factors)
            lines.append(
                f"- **{label} at p/h=100**: modal {item['modal']:.0%} "
                f"(mean factor {item['mean_factor']:.2%}); distribution "
                f"{dist}; unanimous={item['unanimous']}."
            )
    lines += [
        "- The mean-data decision is the Week46/47 table; the seed distribution "
        "shows whether that decision is a sharp boundary or a near-tie. "
        "Disagreement means the threshold should be read as a region, not a "
        "single percentage.",
        "- The 90 cells vary arrival/pick noise, not demand: demand, stock "
        "shares, layout and promises are fixed. This is decision uncertainty, "
        "not out-of-sample demand evidence.",
        "- Holding cost is illustrative and backlog is a shortage proxy; no "
        "lost-sales, goodwill, markdown, working-capital or lead-time cost.",
    ]
    return "\n".join(lines) + "\n"


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
