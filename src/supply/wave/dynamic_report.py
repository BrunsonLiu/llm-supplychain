"""Markdown + JSON report for the Week-8 online wave release benchmark."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from .schedule_report import _json_safe, _md_table, _num, _pct


def _scenario_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "方案": row["scenario"],
                "类型": "离线" if row.get("policy") == "offline" else "在线",
                "波次": row["waves"],
                "单均工时": _num(row["labor_per_order"], 2),
                "准时率": _pct(row["on_time_rate"]),
                "迟到单": row["tardy_orders"],
                "迟到订单分钟": _num(row["total_tardiness"], 0),
                "平均等待": _num(row.get("avg_wait"), 1),
                "P90 等待": _num(row.get("p90_wait"), 1),
                "最大等待": _num(row.get("max_wait"), 1),
                "空闲分钟": _num(row["idle_minutes"], 0),
                "Makespan": _num(row["makespan"], 0),
                "加班 (min)": _num(row["overtime"], 0),
            }
            for row in rows
        ]
    )


def _arrival_table(profile: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "承诺层": row["tier"],
                "截单": row["cutoff"],
                "订单": row["orders"],
                "开班前": row["onsite"],
                "开班前占比": _pct(row["onsite_rate"]),
                "班中到达": row["mid_shift"],
                "到达窗口 (min)": _num(row["window"], 0),
                "平均到达": _num(row["mean_arrival"], 1),
                "中位到达": _num(row["median_arrival"], 1),
                "截单后到达": row["after_cutoff"],
            }
            for row in profile
        ]
    )


def _tuning_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "等待窗口 (min)": _num(row["wait_minutes"], 0),
                "最小成波单数": row["min_fill"],
                "波次": row["waves"],
                "单均工时": _num(row["labor_per_order"], 2),
                "准时率": _pct(row["on_time_rate"]),
                "迟到订单分钟": _num(row["total_tardiness"], 0),
                "平均等待": _num(row["avg_wait"], 1),
                "P90 等待": _num(row["p90_wait"], 1),
                "最大等待": _num(row["max_wait"], 1),
                "空闲分钟": _num(row["idle_minutes"], 0),
                "Makespan": _num(row["makespan"], 0),
            }
            for row in rows
        ]
    )


def _load_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "订单数": row["orders"],
                "方案": row["scenario"],
                "波次": row["waves"],
                "单均工时": _num(row["labor_per_order"], 2),
                "准时率": _pct(row["on_time_rate"]),
                "迟到订单分钟": _num(row["total_tardiness"], 0),
                "平均等待": _num(row.get("avg_wait"), 1),
                "空闲分钟": _num(row["idle_minutes"], 0),
                "Makespan": _num(row["makespan"], 0),
            }
            for row in rows
        ]
    )


def _detail_table(rows: List[Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "波次": row["wave"],
                "拣货员": row["picker"],
                "开始": row["start"],
                "结束": row["end"],
                "工时 (min)": _num(row["minutes"], 1),
                "订单": row["orders"],
                "最紧截单": row["deadline"],
                "迟到单": row["late_orders"],
                "最大迟到 (min)": _num(row["max_late"], 0),
            }
            for row in rows
        ]
    )


def build_dynamic_report(
    results: Dict[str, Any],
    title: str = "Online wave release benchmark",
    generated: str = "",
) -> str:
    dataset = results["dataset"]
    arrivals = results["arrivals"]
    settings = results["settings"]
    summary = results["summary"]
    tuning = results.get("tuning", [])
    load_sweep = results.get("load_sweep", [])
    detail = results.get("detail", [])
    rows = {row["key"]: row for row in summary}

    single = rows.get("single")
    fill = rows.get("edf_fill")
    savings = rows.get("savings")
    wait = rows.get("wait")
    aggressive = rows.get("wait_aggressive")
    oracle = rows.get("oracle")

    lines = [
        f"# {title}",
        "",
        f"- Generated: `{generated}`",
        (
            f"- Orders: **{_num(dataset['orders'], 0)}** real invoices / "
            f"**{_num(dataset['lines'], 0)}** lines / "
            f"**{_num(dataset['units'], 0)}** units, week {dataset['week']}"
        ),
        (
            f"- Arrivals: **{_num(arrivals['onsite_orders'], 0)}** orders before "
            f"the 08:00 start and **{_num(arrivals['mid_shift_orders'], 0)}** during "
            f"the shift; per-tier arrival windows are declared assumptions."
        ),
        (
            f"- Shift: **{settings['pickers']} pickers**, "
            f"**{_num(settings['shift_minutes'], 0)} min**; wave cap "
            f"**{dataset['max_orders']} orders / {dataset['max_lines']} lines**. "
            f"Overtime is reported, not constrained."
        ),
        "",
        "## Assumptions",
        "",
        (
            "| Item | Assumption | Note |\n"
            "|---|---|---|\n"
            "| Promise tier mix | 20% / 50% / 30% | No customer-promise data in Online Retail II; tiers are assigned by seeded shuffle. |\n"
            "| Cutoffs | 12:00 / 16:00 / 18:00 | Minutes 240 / 480 / 600 after the 08:00 shift start. |\n"
            f"| On-time arrival share | express {_pct(arrivals['onsite_share']['express'])}, "
            f"standard {_pct(arrivals['onsite_share']['standard'])}, "
            f"economy {_pct(arrivals['onsite_share']['economy'])} | "
            "No order-release timestamps; the rest arrive uniformly inside the tier window. |\n"
            f"| Arrival window | express {_num(arrivals['windows']['express'], 0)} min, "
            f"standard {_num(arrivals['windows']['standard'], 0)} min, "
            f"economy {_num(arrivals['windows']['economy'], 0)} min | "
            "All windows close before the tier cutoff, so no order is late on arrival. |\n"
            "| Pickers | identical workers | No skills, zones, breaks, or absenteeism. |\n"
            f"| Wait policy | window {_num(settings['wait_minutes'], 0)} min, "
            f"fill ≥ {settings['min_fill']} orders | "
            "An idle picker waits only while the candidate wave is below the fill target and the next arrival is inside the window. |\n"
            f"| Wave labor | Week-6 model | Travel at {_num(dataset['travel_m_per_minute'], 1)} m/min, "
            f"{_num(dataset['pick_min_per_line'], 2)} min/line + "
            f"{_num(dataset['pick_min_per_unit'], 2)} min/unit, "
            f"{_num(dataset['setup_min_per_wave'], 1)} min setup/wave. |"
        ),
        "",
        "## Methods",
        "",
        "- **Event-driven simulation**: orders arrive at a known minute; a free picker immediately forms a wave from the arrived-but-unpicked pool. No future order is visible to an online policy.",
        "- **Online single-order**: one invoice per wave, released as soon as a picker is free. This is the no-batching control.",
        "- **Online EDF fill**: take the available order with the earliest cutoff, then fill the wave with same-tier available orders up to wave capacity. The wave is dispatched immediately.",
        "- **Online savings**: re-run the tier-aware Clarke-Wright merge over the available pool and dispatch the cluster containing the earliest order. This uses only past arrivals.",
        "- **Online savings + wait**: same cluster rule, but an idle picker waits up to the declared window while the candidate cluster is below the fill target. The next arrival can join the cluster.",
        "- **Offline reference**: all orders are visible at 08:00; tier-aware savings is solved once and scheduled EDF. It isolates the value of future information for the savings rule, but it is not a lower bound across all batching rules.",
        "",
        "## Arrival profile",
        "",
        _md_table(_arrival_table(arrivals["profile"])),
        "",
        f"Seeded arrival draw: `{arrivals['seed']}`. The arrival window is a policy assumption; Online Retail II has invoice dates, not intra-day release times.",
        "",
        "## Scenario comparison",
        "",
        _md_table(_scenario_table(summary)),
        "",
        "On-time is counted per order against its own cutoff at wave completion. Waiting time is measured from arrival to wave start; idle minutes are paid picker capacity that is not picking.",
        "",
    ]

    if tuning:
        lines.extend(
            [
                "## Wait-policy tuning",
                "",
                "Same order pool, promise plan and arrival draw; only the wait window and fill target change. A zero wait reproduces the no-wait savings policy.",
                "",
                _md_table(_tuning_table(tuning)),
                "",
            ]
        )

    if load_sweep:
        lines.extend(
            [
                "## Load sensitivity",
                "",
                "The same arrival assumptions are applied to progressively larger order pools. Low load tests whether waiting can fill waves without risking service; high load tests the cost of waiting behind a deep backlog.",
                "",
                _md_table(_load_table(load_sweep)),
                "",
            ]
        )

    if detail:
        lines.extend(
            [
                "## Schedule detail — online savings + wait",
                "",
                _md_table(_detail_table(detail)),
                "",
            ]
        )

    lines.extend(["## Interpretation", ""])
    index = 1
    capacity_note = ""
    if load_sweep:
        single_rows = {
            row["orders"]: row for row in load_sweep if row["key"] == "single"
        }
        safe = sorted(
            orders
            for orders, row in single_rows.items()
            if row["on_time_rate"] >= 1.0 - 1e-9
        )
        unsafe = sorted(
            orders
            for orders, row in single_rows.items()
            if row["on_time_rate"] < 1.0 - 1e-9
        )
        if safe and unsafe:
            capacity_note = (
                f" The no-batching control is only safe while capacity is ample: it still "
                f"meets every cutoff at {'/'.join(str(value) for value in safe)} orders, "
                f"but not at {'/'.join(str(value) for value in unsafe)}."
            )
    if single and fill:
        lines.append(
            f"{index}. **Batching, not forecasting, is the first lever.** Releasing one order "
            f"per wave needs {_num(single['labor_per_order'], 2)} min/order and reaches "
            f"{_pct(single['on_time_rate'])} on-time; filling the same arrived pool to wave "
            f"capacity drops it to {_num(fill['labor_per_order'], 2)} min/order and reaches "
            f"{_pct(fill['on_time_rate'])}. The fill rule uses no future information."
            + capacity_note
        )
        index += 1
    if fill and oracle:
        labor_gap = fill["labor_per_order"] - oracle["labor_per_order"]
        relative = labor_gap / oracle["labor_per_order"] if oracle["labor_per_order"] else 0.0
        wave_gap = fill["waves"] - oracle["waves"]
        if abs(relative) <= 0.05 and abs(wave_gap) <= 3:
            lines.append(
                f"{index}. **Online fill is within {_pct(abs(relative))} of the offline "
                f"reference on labor.** The offline reference needs "
                f"{_num(oracle['labor_per_order'], 2)} min/order and {oracle['waves']} waves; "
                f"online EDF fill returns {_num(fill['labor_per_order'], 2)} min/order and "
                f"{fill['waves']} waves, both at {_pct(fill['on_time_rate'])} on-time. The "
                f"reference sees the whole day but uses a different batching rule, so this is "
                f"not a like-for-like comparison, and it is not proof that the online rule is "
                f"optimal."
            )
        else:
            lines.append(
                f"{index}. **The offline reference keeps a {_pct(abs(relative))} labor "
                f"advantage at this load.** It needs {_num(oracle['labor_per_order'], 2)} "
                f"min/order and {oracle['waves']} waves versus "
                f"{_num(fill['labor_per_order'], 2)} min/order and {fill['waves']} waves for "
                f"online fill. The reference uses a different batching rule, so the gap "
                f"mixes information value with rule choice."
            )
        index += 1
    if savings and oracle:
        saved_waves = savings["waves"] - oracle["waves"]
        saved_labor = savings["labor_per_order"] - oracle["labor_per_order"]
        lines.append(
            f"{index}. **Future information is worth something even under the same rule.** "
            f"Seeing all orders at 08:00 saves {saved_waves} waves "
            f"({savings['waves']} → {oracle['waves']}) and {_num(saved_labor, 2)} min/order "
            f"({_num(savings['labor_per_order'], 2)} → "
            f"{_num(oracle['labor_per_order'], 2)}) for the savings rule. The online version "
            f"still reaches {_pct(savings['on_time_rate'])} on-time with "
            f"{_num(savings['total_tardiness'], 0)} late order-minutes, so at this load the "
            f"information gap shows up in labor rather than service."
        )
        index += 1
    if wait and savings:
        gain = savings["labor_per_order"] - wait["labor_per_order"]
        gain_rate = gain / savings["labor_per_order"] if savings["labor_per_order"] else 0.0
        sentence = (
            "**A short wait pays at this load.**"
            if gain_rate >= 0.03
            else "**A short wait buys little at this load.**"
        )
        if abs(wait["on_time_rate"] - savings["on_time_rate"]) <= 1e-9:
            service = f"On-time is unchanged at {_pct(wait['on_time_rate'])}."
        else:
            service = (
                f"On-time moves from {_pct(savings['on_time_rate'])} to "
                f"{_pct(wait['on_time_rate'])}."
            )
        lines.append(
            f"{index}. {sentence} A {_num(settings['wait_minutes'], 0)}-min window with a "
            f"fill target of {settings['min_fill']} changes {savings['waves']} → "
            f"{wait['waves']} waves and saves {_num(gain, 2)} min/order "
            f"({_pct(gain_rate)}), but adds "
            f"{_num(wait['avg_wait'] - savings['avg_wait'], 1)} min of average waiting, "
            f"{_num(wait['idle_minutes'] - savings['idle_minutes'], 0)} idle picker-minutes "
            f"and {_num(wait['makespan'] - savings['makespan'], 0)} minutes of makespan. "
            f"{service}"
        )
        index += 1
    if aggressive and savings:
        gain = savings["labor_per_order"] - aggressive["labor_per_order"]
        gain_rate = gain / savings["labor_per_order"] if savings["labor_per_order"] else 0.0
        if aggressive["on_time_rate"] < 1.0 - 1e-9:
            lines.append(
                f"{index}. **An aggressive wait crosses the service cliff.** Saving "
                f"{_num(gain, 2)} min/order ({_pct(gain_rate)}) costs "
                f"{aggressive['tardy_orders']} tardy orders and "
                f"{_num(aggressive['total_tardiness'], 0)} late order-minutes: on-time falls "
                f"from {_pct(savings['on_time_rate'])} to "
                f"{_pct(aggressive['on_time_rate'])}, and average waiting rises to "
                f"{_num(aggressive['avg_wait'], 1)} min. The wait window is a service-level "
                f"decision, not a free labor knob."
            )
        else:
            lines.append(
                f"{index}. **At this load even an aggressive wait stays on time.** It saves "
                f"{_num(gain, 2)} min/order ({_pct(gain_rate)}) and keeps "
                f"{_pct(aggressive['on_time_rate'])} on-time, but average waiting rises to "
                f"{_num(aggressive['avg_wait'], 1)} min and idle picker-minutes to "
                f"{_num(aggressive['idle_minutes'], 0)}. The service risk is latent, not "
                f"absent: it appears when the backlog grows."
            )
        index += 1
    if load_sweep:
        by_load = {}
        for row in load_sweep:
            by_load.setdefault(row["orders"], {})[row["key"]] = row
        loads_sorted = sorted(by_load)
        if len(loads_sorted) >= 2:
            small, large = loads_sorted[0], loads_sorted[-1]
            small_savings = by_load[small].get("savings")
            large_savings = by_load[large].get("savings")
            small_aggressive = by_load[small].get("wait_aggressive")
            large_aggressive = by_load[large].get("wait_aggressive")
            if small_savings and large_savings and small_aggressive and large_aggressive:
                small_gain = (
                    small_savings["labor_per_order"]
                    - small_aggressive["labor_per_order"]
                )
                large_gain = (
                    large_savings["labor_per_order"]
                    - large_aggressive["labor_per_order"]
                )
                extra = ""
                if len(loads_sorted) >= 3:
                    middle = loads_sorted[len(loads_sorted) // 2]
                    middle_aggressive = by_load[middle].get("wait_aggressive")
                    middle_oracle = by_load[middle].get("oracle")
                    if (
                        middle_aggressive
                        and middle_oracle
                        and middle_aggressive["on_time_rate"] >= 1.0 - 1e-9
                    ):
                        extra = (
                            f" At {middle} orders the aggressive wait is still safe and "
                            f"lands on {middle_aggressive['waves']} waves at "
                            f"{_num(middle_aggressive['labor_per_order'], 2)} min/order, "
                            f"close to the offline reference's {middle_oracle['waves']} "
                            f"waves at {_num(middle_oracle['labor_per_order'], 2)}."
                        )
                lines.append(
                    f"{index}. **The same aggressive wait turns from free to harmful as "
                    f"load rises.** At {small} orders it saves {_num(small_gain, 2)} "
                    f"min/order while staying at {_pct(small_aggressive['on_time_rate'])} "
                    f"on-time.{extra} At {large} orders it saves only "
                    f"{_num(large_gain, 2)} min/order and drops on-time to "
                    f"{_pct(large_aggressive['on_time_rate'])} with "
                    f"{_num(large_aggressive['total_tardiness'], 0)} late order-minutes. "
                    f"The wait window should scale with the backlog instead of being a fixed "
                    f"constant."
                )
                index += 1
    lines.append(
        f"{index}. **The result is a simulation, not a forecast.** Arrival times, onsite "
        f"shares, promise tiers, picker count and labor minutes are declared assumptions. "
        f"The useful claim is conditional: under this arrival process and this capacity, "
        f"immediate fill-to-capacity protects service, while waiting only pays when the "
        f"queue is thin."
    )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            "- Arrival timestamps, per-tier onsite shares and arrival windows are synthetic. Online Retail II records an invoice date, not the minute an order was released to the warehouse.",
            "- The arrival draw is uniform within each tier window; it has no intra-day burstiness, no order cancellations, and no due-date changes after arrival.",
            "- Online policies see the arrived pool only. They do not forecast future arrivals, and they do not re-optimise picker assignment when a wave finishes early.",
            "- The wait rule only considers the next arrival and a single fill target. It is a heuristic, not a dynamic programme over the arrival distribution.",
            "- The offline reference uses the same tier-aware savings rule and EDF; it is not a lower bound on labor or tardiness across all batching rules. The online fill rule can beat it on wave count while losing on travel.",
            "- Pickers are identical and never blocked: no zones, skills, breaks, congestion, replenishment delays, or handover time between waves.",
            "- One trading week, one warehouse layout, one arrival seed, and one promise mix. No stochastic robustness or confidence interval is reported.",
            "- On-time is measured at wave completion against a declared cutoff; last-mile transit and customer-facing delivery promises are outside this layer.",
            "",
        ]
    )
    return "\n".join(lines)


def write_dynamic_report(
    results: Dict[str, Any],
    out_dir: str | Path,
    title: str = "Online wave release benchmark",
) -> Dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    generated = datetime.now(timezone.utc).isoformat()
    report_path = out / "DYNAMIC_WAVE_REPORT.md"
    summary_path = out / "dynamic_wave_summary.json"
    report_path.write_text(
        build_dynamic_report(results, title=title, generated=generated),
        encoding="utf-8",
    )
    payload = {"generated": generated, "title": title, **results}
    summary_path.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"report": report_path, "summary": summary_path}
