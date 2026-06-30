from __future__ import annotations

import json

from app.services.daily_price_bundle_contract import (
    DAILY_PRICE_BAR_PERIOD,
    DAILY_PRICE_BUNDLE_SCHEMA_VERSION,
)
from app.services.daily_price_bundle_reader import (
    StreamingJsonReader,
    read_daily_price_bundle_metadata,
)


def test_daily_price_bundle_metadata_reads_scalar_across_small_chunks(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(StreamingJsonReader, "_CHUNK_SIZE", 3)
    bundle_path = tmp_path / "daily-price-us.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": DAILY_PRICE_BUNDLE_SCHEMA_VERSION,
                "market": "US",
                "as_of_date": "2026-04-18",
                "bar_period": DAILY_PRICE_BAR_PERIOD,
                "source_revision": "daily_prices_us:20260418120000",
                "symbol_count": 123456,
                "rows": [],
            }
        ),
        encoding="utf-8",
    )

    metadata = read_daily_price_bundle_metadata(bundle_path)

    assert metadata["symbol_count"] == 123456
