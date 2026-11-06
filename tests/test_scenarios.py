"""Tests for calibrated scenario generation."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e.scenarios import (  # noqa: E402
    ScenarioConfig,
    build_calibrated_scenarios,
    scenario_diagnostics,
)


def _clean() -> pd.DataFrame:
    rows = []
    countries = ["United Kingdom", "Germany", "France"]
    for week_index, week in enumerate(
        pd.date_range("2025-01-06", periods=6, freq="7D")
    ):
        for sku_index, sku in enumerate(["A", "B", "C"]):
            for country_index, country in enumerate(countries):
                rows.append(
                    {
                        "sku": sku,
                        "country": country,
                        "quantity": 5 + 2 * week_index + sku_index + country_index,
                        "week": week,
                    }
                )
    return pd.DataFrame(rows)


def test_bootstrap_is_valid_and_reproducible() -> None:
    config = ScenarioConfig(
        method="bootstrap", n_scenarios=12, lookback_weeks=4, seed=5
    )
    first = build_calibrated_scenarios(
        _clean(), ["A", "B", "C"], "2025-02-17", 300, config=config
    )
    second = build_calibrated_scenarios(
        _clean(), ["A", "B", "C"], "2025-02-17", 300, config=config
    )
    assert first.demand.shape == (12, 3)
    assert np.isclose(first.weights.sum(), 1.0)
    assert len(set(first.weeks)) == 12
    assert np.array_equal(first.demand, second.demand)
    assert np.all(first.demand >= 0)
    assert np.all(first.serviceable <= first.demand[:, None, :])
    assert np.all(first.demand.sum(axis=1) == 300)


def test_copula_preserves_shape_and_diagnostics() -> None:
    config = ScenarioConfig(
        method="gaussian_copula", n_scenarios=10, lookback_weeks=4, seed=3
    )
    scenarios = build_calibrated_scenarios(
        _clean(), ["A", "B", "C"], "2025-02-17", 250, config=config
    )
    assert scenarios.demand.shape == (10, 3)
    assert np.all(scenarios.demand.sum(axis=1) == 250)
    diagnostics = scenario_diagnostics(scenarios)
    assert diagnostics["n_scenarios"] == 10
    assert diagnostics["weight_sum"] == 1.0
    assert diagnostics["mean_units"] == 250.0
    assert len(diagnostics["mean_per_sku"]) == 3


def test_invalid_config_is_rejected() -> None:
    for kwargs in (
        {"method": "unknown"},
        {"n_scenarios": 1},
        {"lookback_weeks": 1},
        {"residual_sd": -1.0},
    ):
        try:
            ScenarioConfig(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"应拒绝非法配置: {kwargs}")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} scenario tests passed")
