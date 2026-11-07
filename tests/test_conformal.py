"""Tests for split/Mondrian conformal calibration."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from supply.forecasting.conformal import (  # noqa: E402
    ConformalConfig,
    ConformalError,
    evaluate_conformal,
    fit_conformal,
)


def _predictions() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    for sku_index in range(20):
        sku = f"S{sku_index:02d}"
        scale = 10.0 + sku_index * 2.0
        for week_index, week in enumerate(
            pd.date_range("2025-01-06", periods=12, freq="7D")
        ):
            pred = 50.0 + sku_index * 3.0 + week_index
            actual = pred + rng.normal(0.0, 0.5 * scale)
            rows.append(
                {
                    "model": "lightgbm",
                    "fold": 0,
                    "cutoff": week - pd.Timedelta(weeks=1),
                    "sku": sku,
                    "horizon": 1,
                    "week": week,
                    "actual": actual,
                    "pred": pred,
                    "scale": scale,
                }
            )
    return pd.DataFrame(rows)


def test_fit_and_evaluate_coverage() -> None:
    frame = _predictions()
    target = pd.Timestamp("2025-03-10")
    calibrator = fit_conformal(
        frame,
        target,
        ConformalConfig(alpha=0.2, method="mondrian", min_samples=80),
    )
    assert calibrator.n_calibration == 180
    assert calibrator.q_global > 0
    assert calibrator.target_coverage == 0.8
    report = evaluate_conformal(frame, calibrator, target)
    overall = report["overall"]
    assert 0.65 <= overall["empirical_coverage"] <= 0.95
    assert overall["mean_width"] > 0
    assert len(report["detail"]) == 60
    assert report["overall"]["by_week"]


def test_evaluation_respects_calibrator_model_filter() -> None:
    frame = _predictions()
    target = pd.Timestamp("2025-03-10")
    calibrator = fit_conformal(
        frame,
        target,
        ConformalConfig(alpha=0.2, method="global", model="lightgbm", min_samples=80),
    )
    extra = frame.copy()
    extra["model"] = "naive"
    combined = pd.concat([frame, extra], ignore_index=True)
    report = evaluate_conformal(combined, calibrator, target)
    assert report["overall"]["n"] == 60


def test_interval_is_non_negative_and_reproducible() -> None:
    frame = _predictions()
    config = ConformalConfig(alpha=0.1, method="global", min_samples=80)
    first = fit_conformal(frame, "2025-03-10", config)
    second = fit_conformal(frame, "2025-03-10", config)
    assert first.q_global == second.q_global
    interval = first.interval(0.0, sku="S01", scale=10.0)
    assert interval.lower >= 0.0
    assert interval.upper >= interval.lower
    assert interval.width >= 0.0
    assert interval.as_dict()["method"] in {"global", "mondrian", "per_sku"}


def test_insufficient_samples_and_bad_config_are_rejected() -> None:
    frame = _predictions().head(10)
    try:
        fit_conformal(frame, "2025-03-10", ConformalConfig(min_samples=80))
    except ConformalError:
        pass
    else:
        raise AssertionError("样本不足应拒绝")

    for kwargs in (
        {"alpha": 0.0},
        {"method": "unknown"},
        {"min_samples": 5},
        {"n_buckets": 1},
    ):
        try:
            ConformalConfig(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"非法配置应拒绝: {kwargs}")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\n{len(tests)} conformal tests passed")
