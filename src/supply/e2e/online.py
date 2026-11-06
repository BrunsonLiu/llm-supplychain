"""Online policy selection and receding-horizon replay utilities.

This module separates two concerns:

1. ``run_online_bandit``: generic online learning over a finite policy set;
2. ``evaluate_rolling_policies``: a thin adapter that evaluates the existing
   ``run_rolling_policy`` simulator for each candidate.

The bandit's regret is measured against the best *fixed* policy in hindsight,
which is the right baseline for a policy-selection layer. It is not a claim of
full receding-horizon optimisation; that is the job of the stochastic joint
planner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from supply.rl.bandit import BanditPolicy

from .rolling import ROLLING_POLICIES, run_rolling_policy


Evaluator = Callable[[int, Optional[np.ndarray]], float]


@dataclass
class OnlineResult:
    """Result of one online policy-selection episode."""

    choices: List[int]
    rewards: List[float]
    contexts: List[Optional[np.ndarray]]
    policy_names: List[str]
    cumulative_reward: float
    best_fixed_policy: int
    best_fixed_reward: float
    regret: float
    switch_count: int
    summary: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "choices": list(self.choices),
            "rewards": [float(value) for value in self.rewards],
            "cumulative_reward": float(self.cumulative_reward),
            "best_fixed_policy": int(self.best_fixed_policy),
            "best_fixed_reward": float(self.best_fixed_reward),
            "regret": float(self.regret),
            "switch_count": int(self.switch_count),
            "policy_names": list(self.policy_names),
            "summary": dict(self.summary),
        }


def policy_matrix(
    evaluator: Evaluator,
    contexts: Sequence[Optional[np.ndarray]],
    n_policies: int,
) -> np.ndarray:
    """Evaluate every policy on every context; used for hindsight regret."""
    if n_policies < 2:
        raise ValueError("n_policies 至少为 2")
    matrix = np.zeros((len(contexts), n_policies), dtype=float)
    for round_index, context in enumerate(contexts):
        for policy in range(n_policies):
            matrix[round_index, policy] = float(evaluator(policy, context))
    return matrix


def run_online_bandit(
    selector: BanditPolicy,
    contexts: Sequence[Optional[np.ndarray]],
    evaluator: Evaluator,
    policy_names: Optional[Sequence[str]] = None,
    n_rounds: Optional[int] = None,
) -> OnlineResult:
    """Run one online episode and compute hindsight fixed-policy regret.

    ``evaluator`` must be a *simulator* or replay function; the learner only sees
    the reward of the chosen policy. The full matrix is computed afterwards for
    the regret calculation, so it cannot leak into selection.
    """
    if not contexts:
        raise ValueError("contexts 不能为空")
    rounds = len(contexts) if n_rounds is None else int(n_rounds)
    if rounds < 1:
        raise ValueError("n_rounds 必须为正")
    n_actions = int(getattr(selector, "n_actions"))
    names = list(policy_names or [f"policy_{index}" for index in range(n_actions)])
    if len(names) != n_actions:
        raise ValueError("policy_names 长度应等于动作数")

    choices: List[int] = []
    rewards: List[float] = []
    used_contexts: List[Optional[np.ndarray]] = []
    for round_index in range(rounds):
        context = contexts[round_index % len(contexts)]
        action = selector.select(context)
        reward = float(evaluator(action, context))
        selector.update(action, reward, context)
        choices.append(int(action))
        rewards.append(reward)
        used_contexts.append(context)

    full = policy_matrix(
        evaluator,
        [contexts[index % len(contexts)] for index in range(rounds)],
        n_actions,
    )
    fixed = full.sum(axis=0)
    best_fixed = int(np.argmax(fixed))
    cumulative = float(np.sum(rewards))
    best_reward = float(fixed[best_fixed])
    switches = int(
        sum(1 for left, right in zip(choices, choices[1:]) if left != right)
    )
    return OnlineResult(
        choices=choices,
        rewards=rewards,
        contexts=used_contexts,
        policy_names=names,
        cumulative_reward=cumulative,
        best_fixed_policy=best_fixed,
        best_fixed_reward=best_reward,
        regret=best_reward - cumulative,
        switch_count=switches,
        summary={
            "rounds": rounds,
            "mean_reward": cumulative / rounds,
            "best_policy_name": names[best_fixed],
            "action_counts": {
                names[index]: int(choices.count(index)) for index in range(n_actions)
            },
            "selector": getattr(selector, "name", type(selector).__name__),
        },
    )


def evaluate_rolling_policies(
    instance: Any,
    order_day: np.ndarray,
    policies: Sequence[str] = ROLLING_POLICIES,
    metric: str = "otif_rate",
    **kwargs: Any,
) -> Dict[str, Dict[str, Any]]:
    """Evaluate existing rolling policies; returns the full metric payload."""
    unknown = [policy for policy in policies if policy not in ROLLING_POLICIES]
    if unknown:
        raise ValueError(f"未知 rolling 策略: {unknown}")
    results: Dict[str, Dict[str, Any]] = {}
    for policy in policies:
        results[policy] = run_rolling_policy(
            instance,
            order_day,
            policy,
            **kwargs,
        )
    return results


def reward_from_result(result: Dict[str, Any], metric: str = "otif_rate") -> float:
    """Turn a simulator metric into a higher-is-better reward."""
    if metric == "otif_rate":
        return float(result["otif_rate"])
    if metric == "fill_rate":
        return float(result["fill_rate"])
    if metric == "negative_backlog":
        return -float(result["backlog_units"])
    raise ValueError(f"不支持的 reward metric: {metric}")


Planner = Callable[[Any, Sequence[float]], Any]
Simulator = Callable[[Any, Any, float], Tuple[float, Any, Dict[str, Any]]]
Oracle = Callable[[Any, float], Any]


@dataclass
class RecedingHorizonResult:
    """Costs and states from a generic receding-horizon loop."""

    actions: List[Any]
    costs: List[float]
    states: List[Any]
    cumulative_cost: float
    oracle_cost: Optional[float]
    regret: Optional[float]
    summary: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "actions": list(self.actions),
            "costs": [float(value) for value in self.costs],
            "states": list(self.states),
            "cumulative_cost": float(self.cumulative_cost),
            "oracle_cost": (
                None if self.oracle_cost is None else float(self.oracle_cost)
            ),
            "regret": None if self.regret is None else float(self.regret),
            "summary": dict(self.summary),
        }


def run_receding_horizon(
    planner: Planner,
    simulator: Simulator,
    initial_state: Any,
    demands: Sequence[float],
    oracle: Optional[Oracle] = None,
) -> RecedingHorizonResult:
    """Generic receding-horizon loop.

    ``planner(state, history)`` chooses an action *before* seeing the current
    demand. ``simulator(state, action, demand)`` returns ``(cost, next_state,
    info)``. If ``oracle`` is supplied it sees the realised demand and is used
    only for hindsight regret, never by the planner.
    """
    if not demands:
        raise ValueError("demands 不能为空")
    state = initial_state
    history: List[float] = []
    actions: List[Any] = []
    costs: List[float] = []
    states: List[Any] = []
    oracle_costs: List[float] = []
    for demand in demands:
        pre_state = state
        action = planner(pre_state, tuple(history))
        cost, state, _ = simulator(pre_state, action, float(demand))
        actions.append(action)
        costs.append(float(cost))
        states.append(state)
        history.append(float(demand))
        if oracle is not None:
            oracle_action = oracle(pre_state, float(demand))
            oracle_cost, _, _ = simulator(
                pre_state, oracle_action, float(demand)
            )
            oracle_costs.append(float(oracle_cost))
    total = float(sum(costs))
    oracle_total = float(sum(oracle_costs)) if oracle_costs else None
    return RecedingHorizonResult(
        actions=actions,
        costs=costs,
        states=states,
        cumulative_cost=total,
        oracle_cost=oracle_total,
        regret=None if oracle_total is None else total - oracle_total,
        summary={
            "rounds": len(demands),
            "mean_cost": total / len(demands),
            "has_oracle": oracle_total is not None,
        },
    )
