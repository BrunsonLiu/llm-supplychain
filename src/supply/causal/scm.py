"""Structural causal model (SCM) for a weekly inventory decision.

This module implements the *model-based* causal layer:

* a small, explicit DAG for demand -> forecast -> inventory -> OTIF;
* a structural equation system that can sample observational data;
* ``do`` interventions that replace a structural equation;
* a known ground-truth ATE so causal estimators can be benchmarked honestly.

It is intentionally not a claim about the real UCI dataset. The real data has no
randomised inventory assignment, so this SCM is a digital twin whose causal
effects are **model-relative**. See ``docs/research/CAUSAL_ONLINE_RL_BLUEPRINT.md``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


class CausalGraphError(ValueError):
    """Raised when the DAG is malformed or cyclic."""


@dataclass(frozen=True)
class CausalEdge:
    """One directed edge ``source -> target``."""

    source: str
    target: str

    def as_tuple(self) -> Tuple[str, str]:
        return (self.source, self.target)


class CausalDAG:
    """A small validated directed acyclic graph."""

    def __init__(
        self,
        edges: Iterable[CausalEdge | Tuple[str, str]],
        nodes: Optional[Iterable[str]] = None,
    ) -> None:
        parsed = tuple(
            edge if isinstance(edge, CausalEdge) else CausalEdge(*edge)
            for edge in edges
        )
        names: List[str] = []
        if nodes is not None:
            names.extend(str(node) for node in nodes)
        for edge in parsed:
            for name in (edge.source, edge.target):
                if name not in names:
                    names.append(name)
        if not names:
            raise CausalGraphError("DAG 至少需要一个节点")
        if len(set(names)) != len(names):
            raise CausalGraphError("节点名不能重复")
        self._nodes = tuple(names)
        self._edges = parsed
        self._parents: Dict[str, List[str]] = {name: [] for name in self._nodes}
        self._children: Dict[str, List[str]] = {name: [] for name in self._nodes}
        for edge in parsed:
            if edge.source not in self._parents or edge.target not in self._parents:
                raise CausalGraphError(f"边引用了未知节点: {edge}")
            self._parents[edge.target].append(edge.source)
            self._children[edge.source].append(edge.target)
        self.topological_order()

    @property
    def nodes(self) -> Tuple[str, ...]:
        return self._nodes

    @property
    def edges(self) -> Tuple[CausalEdge, ...]:
        return self._edges

    def parents(self, node: str) -> Tuple[str, ...]:
        return tuple(self._parents.get(node, ()))

    def children(self, node: str) -> Tuple[str, ...]:
        return tuple(self._children.get(node, ()))

    def topological_order(self) -> Tuple[str, ...]:
        indegree = {name: len(self._parents[name]) for name in self._nodes}
        queue = [name for name in self._nodes if indegree[name] == 0]
        order: List[str] = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for child in self._children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if len(order) != len(self._nodes):
            raise CausalGraphError("DAG 存在环，无法拓扑排序")
        return tuple(order)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "nodes": list(self._nodes),
            "edges": [edge.as_tuple() for edge in self._edges],
            "topological_order": list(self.topological_order()),
        }


DEFAULT_DAG = CausalDAG(
    edges=(
        ("seasonality", "demand"),
        ("seasonality", "forecast"),
        ("demand", "forecast"),
        ("forecast", "inventory"),
        ("capacity", "inventory"),
        ("forecast", "otif"),
        ("inventory", "otif"),
        ("demand", "otif"),
        ("capacity", "otif"),
        ("promise", "otif"),
        ("inventory", "cost"),
        ("demand", "cost"),
    ),
    nodes=(
        "seasonality",
        "demand",
        "forecast",
        "capacity",
        "inventory",
        "promise",
        "otif",
        "cost",
    ),
)


@dataclass(frozen=True)
class SupplyChainSCMConfig:
    """Structural equations and the known treatment effect.

    ``treatment`` is a binary inventory intervention (high stock vs baseline).
    The outcome is a linear probability of OTIF, so ``true_ate`` is exactly
    ``treatment_effect``. That makes estimator bias easy to measure.
    """

    treatment_effect: float = 0.08
    stock_shift: float = 38.0
    inventory_otif_effect: float = 0.0018
    confounding: float = 1.0
    demand_mean: float = 100.0
    demand_sd: float = 18.0
    noise_sd: float = 0.06
    seed: int = 7

    def __post_init__(self) -> None:
        if not -0.5 <= self.treatment_effect <= 0.5:
            raise ValueError("treatment_effect 应在 [-0.5, 0.5]")
        if self.stock_shift < 0:
            raise ValueError("stock_shift 不能为负")
        if self.inventory_otif_effect < 0:
            raise ValueError("inventory_otif_effect 不能为负")
        if self.confounding < 0:
            raise ValueError("confounding 不能为负")
        if self.demand_mean <= 0 or self.demand_sd <= 0:
            raise ValueError("需求均值和标准差必须为正")
        if self.noise_sd < 0:
            raise ValueError("noise_sd 不能为负")

    @property
    def true_ate(self) -> float:
        """Total effect: direct treatment + inventory mediator channel."""
        return float(
            self.treatment_effect
            + self.stock_shift * self.inventory_otif_effect
        )


@dataclass
class SupplyChainSCM:
    """Sample observational or interventional data from the structural model."""

    config: SupplyChainSCMConfig = field(default_factory=SupplyChainSCMConfig)
    dag: CausalDAG = DEFAULT_DAG
    _rng: np.random.Generator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.config.seed)

    def _noise(self, size: int, scale: float) -> np.ndarray:
        return self._rng.normal(0.0, scale, size=size)

    def _sigmoid(self, value: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(value, -30.0, 30.0)))

    def sample_observational(self, n_units: int = 2000) -> pd.DataFrame:
        """Sample a confounded observational panel.

        Treatment assignment depends on ``forecast`` and ``capacity``; both also
        affect OTIF, so a naive treated-minus-control difference is biased.
        """
        if n_units < 20:
            raise ValueError("n_units 至少为 20")
        rng = self._rng
        cfg = self.config
        season = rng.normal(0.0, 1.0, n_units)
        demand = np.maximum(
            1.0,
            cfg.demand_mean
            + 0.28 * cfg.demand_mean * season
            + self._noise(n_units, cfg.demand_sd),
        )
        forecast = demand + self._noise(n_units, cfg.demand_sd * 0.35)
        capacity = np.maximum(
            20.0,
            0.78 * demand + self._noise(n_units, cfg.demand_sd * 0.6),
        )
        promise = rng.choice([2, 3, 5], size=n_units, p=[0.3, 0.5, 0.2])
        logit = (
            -2.2
            + cfg.confounding
            * (0.035 * (forecast - cfg.demand_mean) - 0.035 * (capacity - 80.0))
            + 0.15 * season
        )
        propensity = np.clip(self._sigmoid(logit), 0.02, 0.98)
        treatment = rng.binomial(1, propensity, size=n_units)
        inventory = np.maximum(
            0.0,
            55.0
            + cfg.stock_shift * treatment
            + 0.22 * forecast
            + self._noise(n_units, 6.0),
        )
        otif = (
            0.55
            + cfg.treatment_effect * treatment
            + cfg.inventory_otif_effect * inventory
            + 0.0010 * capacity
            - 0.0028 * demand
            - 0.006 * (promise - 3)
            + self._noise(n_units, cfg.noise_sd)
        )
        otif = np.clip(otif, 0.0, 1.0)
        cost = (
            1.8 * inventory
            + 0.9 * demand
            + 4.0 * (1.0 - otif) * demand
            + self._noise(n_units, cfg.demand_sd * 0.25)
            + 20.0
        )
        return pd.DataFrame(
            {
                "seasonality": season,
                "demand": demand,
                "forecast": forecast,
                "capacity": capacity,
                "promise": promise,
                "propensity": propensity,
                "treatment": treatment,
                "inventory": inventory,
                "otif": otif,
                "cost": cost,
            }
        )

    def sample_interventional(
        self,
        treatment: int,
        n_units: int = 2000,
        seed: Optional[int] = None,
    ) -> pd.DataFrame:
        """Sample under ``do(treatment=t)``.

        Covariates keep their observational distribution; the treatment equation
        is replaced by the constant ``t``. This is a model-level intervention,
        not a real-world experiment.
        """
        if treatment not in (0, 1):
            raise ValueError("treatment 只能为 0 或 1")
        if seed is not None:
            self._rng = np.random.default_rng(seed)
        rng = self._rng
        cfg = self.config
        season = rng.normal(0.0, 1.0, n_units)
        demand = np.maximum(
            1.0,
            cfg.demand_mean
            + 0.28 * cfg.demand_mean * season
            + self._noise(n_units, cfg.demand_sd),
        )
        forecast = demand + self._noise(n_units, cfg.demand_sd * 0.35)
        capacity = np.maximum(
            20.0,
            0.78 * demand + self._noise(n_units, cfg.demand_sd * 0.6),
        )
        promise = rng.choice([2, 3, 5], size=n_units, p=[0.3, 0.5, 0.2])
        inventory = np.maximum(
            0.0,
            55.0
            + cfg.stock_shift * treatment
            + 0.22 * forecast
            + self._noise(n_units, 6.0),
        )
        otif = (
            0.55
            + cfg.treatment_effect * treatment
            + cfg.inventory_otif_effect * inventory
            + 0.0010 * capacity
            - 0.0028 * demand
            - 0.006 * (promise - 3)
            + self._noise(n_units, cfg.noise_sd)
        )
        otif = np.clip(otif, 0.0, 1.0)
        cost = (
            1.8 * inventory
            + 0.9 * demand
            + 4.0 * (1.0 - otif) * demand
            + self._noise(n_units, cfg.demand_sd * 0.25)
            + 20.0
        )
        return pd.DataFrame(
            {
                "seasonality": season,
                "demand": demand,
                "forecast": forecast,
                "capacity": capacity,
                "promise": promise,
                "treatment": np.full(n_units, int(treatment)),
                "inventory": inventory,
                "otif": otif,
                "cost": cost,
            }
        )

    def true_ate_from_simulation(
        self,
        n_units: int = 20000,
        seed: int = 123,
    ) -> float:
        """Monte-Carlo truth under the SCM; useful as a sanity check."""
        # Same seed for both arms pairs covariates and noise, so the difference
        # estimates the total effect instead of adding Monte-Carlo noise.
        treated = self.sample_interventional(1, n_units=n_units, seed=seed)
        control = self.sample_interventional(0, n_units=n_units, seed=seed)
        return float(treated["otif"].mean() - control["otif"].mean())

    def do(self, treatment: int, n_units: int = 2000) -> pd.DataFrame:
        """Alias for ``sample_interventional`` with explicit do-notation."""
        return self.sample_interventional(treatment=treatment, n_units=n_units)


def simple_dag() -> CausalDAG:
    """Convenience export for tests and docs."""
    return DEFAULT_DAG
