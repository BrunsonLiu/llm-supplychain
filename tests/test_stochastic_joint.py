"""Tests for the cost-aware stochastic joint model."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e.stochastic import DemandScenario, ScenarioSet  # noqa: E402
from supply.e2e.stochastic_joint import solve_stochastic_joint  # noqa: E402


def _problem():
    n_dcs, n_skus, n_scenarios = 2, 2, 2
    fulfillment = SimpleNamespace(
        n_dcs=n_dcs,
        n_skus=n_skus,
        stock=np.array([[6, 4], [4, 6]], dtype=np.int64),
        dc_capacity=np.array([20, 20], dtype=np.int64),
    )
    instance = SimpleNamespace(fulfillment=fulfillment)
    demand = np.array([[8, 6], [4, 10]], dtype=np.int64)
    serviceable = np.stack(
        [np.tile(demand[scenario], (n_dcs, 1)) for scenario in range(n_scenarios)]
    )
    scenarios = tuple(
        DemandScenario(
            week=f"w{scenario}",
            weight=1.0 / n_scenarios,
            demand=demand[scenario],
            serviceable=serviceable[scenario],
            raw_units=int(demand[scenario].sum()),
            scale=1.0,
            history_lines=1,
            active_skus=int((demand[scenario] > 0).sum()),
        )
        for scenario in range(n_scenarios)
    )
    scenario_set = ScenarioSet(
        scenarios=scenarios,
        sku_names=("A", "B"),
        dc_names=("L", "R"),
        target_units=int(demand.sum()),
        promise_shares=((2, 0.3), (3, 0.5), (5, 0.2)),
    )
    return instance, scenario_set


def test_joint_plan_is_feasible_and_costed() -> None:
    instance, scenarios = _problem()
    plan = solve_stochastic_joint(
        instance,
        scenarios,
        cvar_weight=0.5,
        alpha=0.8,
        time_limit_seconds=10,
        workers=2,
    )
    assert plan.status in {"OPTIMAL", "FEASIBLE"}
    assert np.array_equal(plan.stock.sum(axis=0), np.array([10, 10]))
    assert plan.allocation.shape == (2, 2, 2)
    assert np.all(plan.allocation.sum(axis=1) <= scenarios.demand)
    assert np.isfinite(plan.expected_cost)
    assert np.isfinite(plan.cvar_cost)
    assert abs(plan.objective - plan.solver_objective) < 1e-6
    assert plan.gap >= 0.0


def test_risk_neutral_and_risk_averse_are_valid() -> None:
    instance, scenarios = _problem()
    for weight in (0.0, 1.0):
        plan = solve_stochastic_joint(
            instance,
            scenarios,
            cvar_weight=weight,
            alpha=0.9,
            time_limit_seconds=10,
            workers=2,
        )
        assert plan.cvar_weight == weight
        assert np.isfinite(plan.objective)


def test_invalid_scenario_shape_is_rejected() -> None:
    instance, scenarios = _problem()
    bad = SimpleNamespace(
        demand=scenarios.demand,
        serviceable=scenarios.serviceable[:, :1, :],
        weights=scenarios.weights,
        dc_names=scenarios.dc_names,
        sku_names=scenarios.sku_names,
    )
    try:
        solve_stochastic_joint(instance, bad, time_limit_seconds=2)
    except ValueError:
        pass
    else:
        raise AssertionError("错误场景形状应被拒绝")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} stochastic-joint tests passed")
