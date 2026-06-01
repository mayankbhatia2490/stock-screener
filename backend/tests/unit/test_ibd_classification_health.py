"""Unit tests for the IBD classification health report + gate (pure, no DB)."""
from app.services.ibd_classification_health import (
    HISTOGRAM_BINS,
    confidence_histogram,
    diff_classifications,
)


def test_confidence_histogram_bins_and_null():
    rows = [
        {"confidence": 0.91},   # -> [0.9,1.0]
        {"confidence": 1.0},    # -> [0.9,1.0] (clamped)
        {"confidence": 0.8},    # -> [0.8,0.9)
        {"confidence": 0.05},   # -> [0.0,0.1)
        {"confidence": None},   # -> null (LLM rows carry no confidence)
    ]
    hist = confidence_histogram(rows)

    assert hist["[0.9,1.0]"] == 2
    assert hist["[0.8,0.9)"] == 1
    assert hist["[0.0,0.1)"] == 1
    assert hist["null"] == 1
    # Every bin is always present (zero-initialised) plus the null bucket.
    assert set(hist) == set(HISTOGRAM_BINS) | {"null"}
    # Counts sum to the row count.
    assert sum(hist.values()) == len(rows)


def test_diff_classifications_counts_and_churn():
    prev = [
        {"symbol": "A", "industry_group": "G1"},
        {"symbol": "B", "industry_group": "G2"},
        {"symbol": "C", "industry_group": "G3"},  # removed next week
    ]
    new = [
        {"symbol": "A", "industry_group": "G1"},  # unchanged
        {"symbol": "B", "industry_group": "G9"},  # changed group
        {"symbol": "D", "industry_group": "G4"},  # added
    ]

    diff = diff_classifications(prev, new)

    assert diff["compared"] == 2          # A, B present both weeks
    assert diff["changed_group"] == 1     # B
    assert diff["added"] == 1             # D
    assert diff["removed"] == 1           # C
    assert diff["churn_pct"] == 50.0      # 1 changed / 2 compared
    assert {"symbol": "B", "prev": "G2", "new": "G9"} in diff["changed_examples"]


def test_diff_classifications_empty_prev_is_zero_churn():
    diff = diff_classifications([], [{"symbol": "A", "industry_group": "G1"}])
    assert diff["compared"] == 0
    assert diff["added"] == 1
    assert diff["churn_pct"] == 0.0
