"""Tests for online policy selection and the RL-0 bandits."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.e2e.online import (  # noqa: E402
    evaluate_rolling_policies,
    policy_matrix,
    reward_from_result,
    run_online_bandit,
    run_receding_horizon,
)
from supply.rl.bandit import (  # noqa: E402
    BanditError,
    EpsilonGreedy,
    LinUCB,
    SlidingWindowUCB,
    ThompsonSampling,
    UCB1,
    make_policy,
)
from supply.rl.ope import doubly_robust, ips  # noqa: E402


def _evaluator(best: int = 1, n_actions: int = 3):
    def evaluate(action: int, context) -> float:
        return 1.0 if action == best else 0.0

    return evaluate


def test_ucb_and_thompson_learn_best_arm() -> None:
    contexts = [None] * 120
    for selector in (
        UCB1(3, exploration=1.0),
        ThompsonSampling(3, seed=4),
        EpsilonGreedy(3, epsilon=0.05, seed=4),
        SlidingWindowUCB(3, window=40, exploration=1.0),
    ):
        result = run_online_bandit(
            selector,
            contexts,
            _evaluator(best=1),
            policy_names=["a", "b", "c"],
        )
        assert result.cumulative_reward >= 80
        assert result.regret <= 40
        assert result.best_fixed_policy == 1
        counts = [result.choices.count(index) for index in range(3)]
        assert counts[1] >= max(counts[0], counts[2])


def test_policy_matrix_shape_and_values() -> None:
    matrix = policy_matrix(_evaluator(best=2), [None, None, None], 3)
    assert matrix.shape == (3, 3)
    assert np.allclose(matrix[:, 2], 1.0)
    assert np.allclose(matrix[:, :2], 0.0)


def test_linucb_accepts_context_and_learns_a_separable_arm() -> None:
    selector = LinUCB(2, n_features=2, alpha=0.05, ridge=1.0)
    contexts = [
        np.array([1.0, 0.0]),
        np.array([0.0, 1.0]),
    ] * 60
    for context in contexts:
        action = selector.select(context)
        best = 0 if context[0] > 0.5 else 1
        selector.update(action, 1.0 if action == best else 0.0, context)
    # The signal is separable; after 120 observations the learned policy should
    # prefer the correct arm at least once on each context.
    assert selector.select(np.array([1.0, 0.0])) == 0
    assert selector.select(np.array([0.0, 1.0])) == 1


def test_invalid_bandit_inputs_are_rejected() -> None:
    for call in (
        lambda: UCB1(1),
        lambda: EpsilonGreedy(2, epsilon=1.5),
        lambda: SlidingWindowUCB(2, window=0),
        lambda: LinUCB(2, n_features=0),
        lambda: make_policy("unknown", 2),
    ):
        try:
            call()
        except (ValueError, BanditError):
            continue
        raise AssertionError("非法 bandit 配置应被拒绝")


def test_reward_adapter() -> None:
    assert reward_from_result({"otif_rate": 0.4}) == 0.4
    assert reward_from_result({"fill_rate": 0.6}, metric="fill_rate") == 0.6
    assert reward_from_result({"backlog_units": 7}, metric="negative_backlog") == -7.0


def test_rolling_policy_errors_can_be_reported(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("UNKNOWN")

    monkeypatch.setattr("supply.e2e.online.run_rolling_policy", fail)
    results = evaluate_rolling_policies(
        object(),
        np.zeros(1, dtype=int),
        policies=("daily_1d",),
        raise_errors=False,
    )
    assert "error" in results["daily_1d"]
    assert "UNKNOWN" in results["daily_1d"]["error"]


def test_off_policy_evaluation_recovers_target_value() -> None:
    rng = np.random.default_rng(2)
    n = 1500
    actions = rng.integers(0, 3, size=n)
    segment = rng.integers(0, 2, size=n)
    rewards = (actions == segment + 1).astype(float)
    logs = pd.DataFrame(
        {
            "action": actions,
            "reward": rewards,
            "propensity": np.full(n, 1.0 / 3.0),
            "segment": segment,
        }
    )

    def target(row) -> np.ndarray:
        probs = np.zeros(3)
        probs[int(row["segment"]) + 1] = 1.0
        return probs

    value = ips(logs, target)
    assert abs(value.value - 1.0) < 0.05
    assert value.ci_low <= 1.0 <= value.ci_high
    assert value.effective_sample_size > 0

    q_hat = np.zeros((n, 3))
    q_hat[np.arange(n), segment + 1] = 1.0
    dr = doubly_robust(logs, target, q_hat)
    assert abs(dr.value - 1.0) < 0.05


def test_receding_horizon_uses_feedback_and_hindsight_oracle() -> None:
    def planner(state, history):
        target = 10
        return max(0, target - state)

    def simulator(state, action, demand):
        available = state + action
        served = min(available, demand)
        backlog = demand - served
        next_state = available - served
        cost = backlog * 5.0 + max(0, next_state) * 0.1
        return cost, next_state, {"served": served}

    def oracle(state, demand):
        return max(0, demand - state)

    result = run_receding_horizon(
        planner,
        simulator,
        initial_state=3,
        demands=[5.0, 7.0, 6.0],
        oracle=oracle,
    )
    assert result.cumulative_cost >= 0
    assert result.oracle_cost == 0.0
    assert result.regret == result.cumulative_cost
    assert result.summary["rounds"] == 3
    assert len(result.actions) == 3


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} online/RL tests passed")
