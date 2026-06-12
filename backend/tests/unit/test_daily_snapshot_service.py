"""Unit tests for the aggregated Daily Snapshot service helpers."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services.daily_snapshot_service import (
    DAILY_SNAPSHOT_SCHEMA_VERSION,
    _scan_freshness,
    daily_snapshot_cache_key,
    daily_snapshot_etag,
)
from app.services.price_refresh_plan_builder import _key_market_refresh_symbols


def _norm(market):
    return str(market).upper()


class TestKeyMarketRefreshSymbols:
    def test_us_includes_aliased_data_symbols(self):
        symbols = _key_market_refresh_symbols("US", _norm)
        # TradingView display symbols must be resolved to fetchable Yahoo symbols
        assert "BTC-USD" in symbols
        assert "^VIX" in symbols
        assert "DX-Y.NYB" in symbols
        assert "SGD=X" in symbols
        assert all(market == "US" for market in symbols.values())
        # Display-only symbols never leak into the refresh plan
        assert "BITSTAMP:BTCUSD" not in symbols
        assert "TVC:VIX" not in symbols

    def test_none_market_spans_all_markets(self):
        symbols = _key_market_refresh_symbols(None, _norm)
        assert symbols["BTC-USD"] == "US"
        assert symbols["2800.HK"] == "HK"
        assert symbols["^N225"] == "JP"

    def test_unknown_market_is_empty(self):
        assert _key_market_refresh_symbols("XX", _norm) == {}


class TestSnapshotCacheHelpers:
    def test_cache_key_is_market_scoped_and_versioned(self):
        key = daily_snapshot_cache_key("us")
        assert key == f"daily_snapshot:v{DAILY_SNAPSHOT_SCHEMA_VERSION}:US"

    def test_etag_is_stable_and_weak(self):
        first = daily_snapshot_etag('{"a":1}')
        second = daily_snapshot_etag('{"a":1}')
        assert first == second
        assert first.startswith('W/"')
        assert daily_snapshot_etag('{"a":2}') != first


class TestScanFreshness:
    def test_no_scan(self):
        freshness = _scan_freshness(None)
        assert freshness == {
            "scan_id": None,
            "scan_as_of_date": None,
            "scan_published_at": None,
        }

    def test_scan_with_feature_run(self):
        run = SimpleNamespace(
            as_of_date=date(2026, 6, 10),
            published_at=datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc),
        )
        scan = SimpleNamespace(
            scan_id="abc-123",
            feature_run=run,
            completed_at=datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc),
        )
        freshness = _scan_freshness(scan)
        assert freshness["scan_id"] == "abc-123"
        assert freshness["scan_as_of_date"] == "2026-06-10"
        assert freshness["scan_published_at"].startswith("2026-06-10T23:00")

    def test_scan_without_feature_run_falls_back_to_completed_at(self):
        scan = SimpleNamespace(
            scan_id="abc-456",
            feature_run=None,
            completed_at=datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc),
        )
        freshness = _scan_freshness(scan)
        assert freshness["scan_as_of_date"] == "2026-06-11"
        assert freshness["scan_published_at"].startswith("2026-06-11T01:00")
