"""Tests for the SCM and causal estimators."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.causal import (  # noqa: E402
    CausalBenchmarkConfig,
    CausalDAG,
    CausalGraphError,
    SupplyChainSCM,
    SupplyChainSCMConfig,
    aipw,
    dml,
    estimate_all,
    ipw,
    naive_difference,
    run_estimator_benchmark,
)


def test_dag_topological_order_and_cycle() -> None:
    dag = CausalDAG([("a", "b"), ("b", "c"), ("a", "c")], nodes=["a", "b", "c"])
    assert dag.topological_order() == ("a", "b", "c")
    assert dag.parents("c") == ("b", "a")
    assert dag.children("a") == ("b", "c")
    assert dag.as_dict()["edges"] == [("a", "b"), ("b", "c"), ("a", "c")]

    try:
        CausalDAG([("a", "b"), ("b", "a")])
    except CausalGraphError:
        pass
    else:
        raise AssertionError("环应被拒绝")


def test_scm_reproducible_and_known_ate() -> None:
    config = SupplyChainSCMConfig(seed=11)
    first = SupplyChainSCM(config).sample_observational(500)
    second = SupplyChainSCM(config).sample_observational(500)
    pd.testing.assert_frame_equal(first, second)

    scm = SupplyChainSCM(config)
    simulated = scm.true_ate_from_simulation(n_units=5000, seed=123)
    assert abs(simulated - config.true_ate) < 0.01
    assert 0.0 <= first["otif"].min() <= first["otif"].max() <= 1.0
    assert set(first["treatment"].unique()) <= {0, 1}
    assert first["propensity"].between(0, 1).all()


def test_naive_is_biased_and_doubly_robust_recovers_truth() -> None:
    config = SupplyChainSCMConfig(seed=7)
    data = SupplyChainSCM(config).sample_observational(4000)
    truth = config.true_ate

    naive = naive_difference(data)
    robust = aipw(data)
    weighted = ipw(data)
    debiased = dml(data)

    assert abs(naive.estimate - truth) > abs(robust.estimate - truth)
    assert abs(weighted.estimate - truth) < 0.03
    assert abs(robust.estimate - truth) < 0.03
    assert abs(debiased.estimate - truth) < 0.03
    assert robust.ci_low <= truth <= robust.ci_high
    assert weighted.ci_low <= truth <= weighted.ci_high


def test_estimate_all_reports_finite_outputs() -> None:
    data = SupplyChainSCM(SupplyChainSCMConfig(seed=3)).sample_observational(800)
    estimates = estimate_all(data)
    assert {item.method for item in estimates} == {"naive", "ipw", "aipw", "dml"}
    assert all(np.isfinite(item.estimate) for item in estimates)
    assert all(item.n == len(data) for item in estimates)


def test_benchmark_summary_and_limitations() -> None:
    result = run_estimator_benchmark(
        CausalBenchmarkConfig(n_units=800, n_replicates=2, seed=5)
    )
    assert result.summary["method"].tolist()
    assert {"mean_abs_bias", "coverage", "mean_ci_width"} <= set(result.summary)
    payload = result.as_dict()
    assert payload["truth"] > 0
    assert payload["limitations"]
    assert payload["dag"]["edges"]


def test_invalid_inputs_are_rejected() -> None:
    data = pd.DataFrame(
        {
            "treatment": [0, 1, 0, 1],
            "otif": [0.2, 0.3, 0.4, 0.5],
        }
    )
    broken = data.drop(columns=["otif"])
    for function in (ipw, aipw, dml):
        try:
            function(broken, covariates=())
        except Exception:
            continue
        raise AssertionError(f"{function.__name__} 应拒绝缺少 outcome 的输入")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} causal tests passed")
