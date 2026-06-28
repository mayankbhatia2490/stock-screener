"""Tests for partial-history scan-row metrics."""

from __future__ import annotations

import pandas as pd
import pytest

from app.scanners.partial_history_metrics import _calculate_price_change_1d


@pytest.mark.parametrize(
    "values",
    [
        [pd.NA, 101.0],
        [100.0, pd.NA],
    ],
)
def test_price_change_handles_pandas_nullable_scalars(values):
    close = pd.Series(values, dtype="Float64")

    assert _calculate_price_change_1d(close) is None
