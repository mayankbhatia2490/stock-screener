"""Regression tests for RSSparklineCalculator.

The CN static-site page showed a large spike on the latest bar across all
scan/group sparklines. Root cause: a single non-finite element in the raw
``stock / benchmark`` ratio was rewritten to ``1.0`` by ``np.nan_to_num``,
and the subsequent ``rs_ratio / rs_ratio[0]`` normalization amplified it
because CN's raw ratio (CNY stock / CSI 300) is ~0.01, so the planted 1.0
became a ~100x spike. The tests below pin the trailing-bar contamination
cases that produced the visible artifact.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from app.scanners.criteria.rs_sparkline import RSSparklineCalculator


def _cn_like_series(seed: int = 42, length: int = 40):
    """Build CN-shaped (small ratio) stock/benchmark series for spike checks."""
    import numpy as np

    rng = np.random.default_rng(seed)
    stock = pd.Series(50 + np.cumsum(rng.standard_normal(length) * 0.5))
    benchmark = pd.Series(4000 + np.cumsum(rng.standard_normal(length) * 5))
    return stock, benchmark


def test_benchmark_nan_on_latest_bar_does_not_spike():
    stock, benchmark = _cn_like_series()
    benchmark.iloc[-1] = float("nan")

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is not None
    assert len(result["rs_data"]) == 30
    for value in result["rs_data"]:
        assert math.isfinite(value)
    # Trailing bar must flatten to the leading level (1.0 after normalization)
    # rather than reproduce the historical ~76x spike from the 1.0 substitute.
    assert result["rs_data"][-1] < 5.0


def test_benchmark_zero_on_latest_bar_does_not_spike():
    stock, benchmark = _cn_like_series()
    benchmark.iloc[-1] = 0.0

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is not None
    for value in result["rs_data"]:
        assert math.isfinite(value)
    assert result["rs_data"][-1] < 5.0


def test_stock_nan_on_latest_bar_does_not_spike():
    stock, benchmark = _cn_like_series()
    stock.iloc[-1] = float("nan")

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is not None
    for value in result["rs_data"]:
        assert math.isfinite(value)
    assert result["rs_data"][-1] < 5.0


def test_all_nan_stock_returns_none_payload():
    stock = pd.Series([float("nan")] * 30)
    benchmark = pd.Series([4000.0 + i for i in range(30)])

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is None
    assert result["rs_trend"] == 0


def test_all_inf_stock_returns_none_payload():
    # finite / inf = 0.0 (still finite), so an all-inf benchmark collapses the
    # series to zeros rather than non-finite. The user-visible failure mode is
    # an all-inf stock series, which yields nan after division.
    stock = pd.Series([math.inf] * 30)
    benchmark = pd.Series([4000.0 + i for i in range(30)])

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is None


def test_leading_nan_uses_first_finite_fill():
    # Build a 30-element series so the leading NaNs land inside the iloc[-30:]
    # window the calculator slices — a longer series would push them out and
    # leave the fill path untested.
    stock = pd.Series([float("nan")] * 5 + [50.0 + i * 0.1 for i in range(25)])
    benchmark = pd.Series([4000.0 + i for i in range(30)])

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is not None
    assert len(result["rs_data"]) == 30
    for value in result["rs_data"]:
        assert math.isfinite(value)
    # Leading NaN entries should be filled with the first finite RS ratio,
    # which equals rs_ratio[0] after normalization → 1.0.
    for value in result["rs_data"][:5]:
        assert value == pytest.approx(1.0)


def test_clean_input_still_produces_finite_normalized_series():
    stock = pd.Series([50.0 + i * 0.1 for i in range(30)])
    benchmark = pd.Series([4000.0 + i for i in range(30)])

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is not None
    assert len(result["rs_data"]) == 30
    assert result["rs_data"][0] == pytest.approx(1.0)


def test_insufficient_data_returns_none():
    stock = pd.Series([50.0] * 10)
    benchmark = pd.Series([4000.0] * 10)

    result = RSSparklineCalculator().calculate_rs_sparkline(stock, benchmark)

    assert result["rs_data"] is None
    assert result["rs_trend"] == 0
