"""Tests for the transportation LP/MIP and dual extraction."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.network.transport import (  # noqa: E402
    TransportInstance,
    TransportSolverError,
    solve_transport_lp,
    solve_transport_mip,
)


def _instance() -> TransportInstance:
    return TransportInstance(
        supply=np.array([10.0, 10.0]),
        demand=np.array([8.0, 7.0]),
        cost=np.array([[1.0, 2.0], [3.0, 1.0]]),
        shortage_penalty=100.0,
        capacity=np.array([10.0, 10.0]),
        fixed_cost=np.array([5.0, 5.0]),
    )


def test_lp_glop_objective_and_duals() -> None:
    result = solve_transport_lp(_instance())
    assert result.solver == "glop"
    assert result.status == "OPTIMAL"
    assert result.objective == pytest.approx(15.0)
    assert result.flows.shape == (2, 2)
    assert result.demand_duals.shape == (2,)
    assert result.supply_duals.shape == (2,)
    assert np.all(np.isfinite(result.demand_duals))
    assert np.all(np.isfinite(result.supply_duals))
    assert result.unmet.sum() == pytest.approx(0.0)


def test_lp_shortage_penalty_handles_infeasibility() -> None:
    instance = TransportInstance(
        supply=np.array([1.0]),
        demand=np.array([3.0]),
        cost=np.array([[1.0]]),
        shortage_penalty=10.0,
    )
    result = solve_transport_lp(instance)
    assert result.unmet.sum() == pytest.approx(2.0)
    assert result.demand_duals[0] == pytest.approx(10.0)


def test_mip_scip_fixed_charge() -> None:
    result = solve_transport_mip(_instance())
    assert result.solver == "scip"
    assert result.status in {"OPTIMAL", "FEASIBLE"}
    assert result.objective >= 15.0
    assert result.fixed_cost >= 0.0
    assert result.open_dcs
    assert result.flows.shape == (2, 2)


def test_gurobi_adapters_when_available() -> None:
    try:
        lp = solve_transport_lp(_instance(), solver="gurobi")
        mip = solve_transport_mip(_instance(), solver="gurobi")
    except TransportSolverError as exc:
        pytest.skip(f"Gurobi 不可用/无许可证: {exc}")
    assert lp.objective == pytest.approx(15.0, abs=1e-5)
    assert lp.solver == "gurobi"
    assert mip.objective >= 15.0


def test_invalid_shapes_are_rejected() -> None:
    for kwargs in (
        {"supply": np.array([1.0]), "demand": np.array([1.0]), "cost": np.zeros((2, 2))},
        {
            "supply": np.array([-1.0]),
            "demand": np.array([1.0]),
            "cost": np.ones((1, 1)),
        },
        {
            "supply": np.array([1.0]),
            "demand": np.array([1.0]),
            "cost": np.ones((1, 1)),
            "shortage_penalty": 0.0,
        },
    ):
        try:
            TransportInstance(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"非法实例应拒绝: {kwargs}")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} transport tests passed")

