"""Health scorecard + regression gate for IBD classification bundles.

Pure functions (no DB, no network): given the freshly-built bundle payload and,
optionally, the previous week's payload, produce a per-market health report —
coverage, tier mix, a confidence histogram, the embedding-model fingerprint, and
a week-over-week churn diff — and evaluate it against configurable thresholds.

The report is published as the ``ibd-classification-health-<market>.json`` release
asset next to the bundle/manifest. The gate runs at build time so a regression is
blocked before the new bundle is uploaded; the prior good ``-latest`` manifest then
stays referenced and the static-site build falls back to it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

HEALTH_REPORT_SCHEMA_VERSION = 1

HISTOGRAM_BINS = [
    "[0.0,0.1)", "[0.1,0.2)", "[0.2,0.3)", "[0.3,0.4)", "[0.4,0.5)",
    "[0.5,0.6)", "[0.6,0.7)", "[0.7,0.8)", "[0.8,0.9)", "[0.9,1.0]",
]


def confidence_histogram(rows: Iterable[dict]) -> dict[str, int]:
    """Bucket assignment confidences into ten 0.1-width bins plus a null bucket.

    crosswalk/embedding rows carry a float confidence; llm rows carry None.
    """
    hist: dict[str, int] = {b: 0 for b in HISTOGRAM_BINS}
    hist["null"] = 0
    for row in rows:
        confidence = row.get("confidence")
        if confidence is None:
            hist["null"] += 1
            continue
        if confidence >= 1.0:
            hist[HISTOGRAM_BINS[-1]] += 1
            continue
        idx = int(confidence * 10)
        idx = max(0, min(idx, 9))
        hist[HISTOGRAM_BINS[idx]] += 1
    return hist


def diff_classifications(prev_rows: Iterable[dict], new_rows: Iterable[dict]) -> dict:
    """Compare two weeks of classifications keyed by symbol.

    ``churn_pct`` is the share of symbols *present in both weeks* whose industry
    group changed — the signal for "did classifications shift unexpectedly".
    Symbols added/removed across weeks are reported separately so a normal
    universe refresh isn't mistaken for churn.
    """
    prev = {r["symbol"]: r.get("industry_group") for r in prev_rows}
    new = {r["symbol"]: r.get("industry_group") for r in new_rows}
    prev_keys, new_keys = set(prev), set(new)
    common = prev_keys & new_keys
    changed = sorted(s for s in common if prev[s] != new[s])
    compared = len(common)
    return {
        "compared": compared,
        "added": len(new_keys - prev_keys),
        "removed": len(prev_keys - new_keys),
        "changed_group": len(changed),
        "churn_pct": round(100.0 * len(changed) / compared, 2) if compared else 0.0,
        "changed_examples": [
            {"symbol": s, "prev": prev[s], "new": new[s]} for s in changed[:50]
        ],
    }
