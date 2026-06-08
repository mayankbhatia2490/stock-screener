from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from app.models.stock import StockPrice


class _GithubService:
    def __init__(self, sync_result, missing_symbols=None):
        self.sync_calls = []
        self.missing_calls = []
        self.sync_result = sync_result
        self.missing_symbols = list(missing_symbols or [])

    def sync_from_github(self, db, **kwargs):
        self.sync_calls.append(kwargs)
        return self.sync_result

    def symbols_missing_as_of(self, db, *, symbols, as_of_date):
        self.missing_calls.append({"symbols": list(symbols), "as_of_date": as_of_date})
        return list(self.missing_symbols)


def _calendar(day: date):
    return SimpleNamespace(last_completed_trading_day=lambda _market: day)


def test_price_history_coverage_splits_fresh_stale_and_no_history(universe_session):
    from app.services.price_refresh_planning import classify_price_history

    universe_session.add_all(
        [
            StockPrice(symbol="0700.HK", date=date(2026, 6, 5), close=100),
            StockPrice(symbol="0005.HK", date=date(2026, 6, 8), close=50),
        ]
    )
    universe_session.commit()

    coverage = classify_price_history(
        universe_session,
        symbols=["0700.HK", "0005.HK", "9999.HK"],
        as_of_date=date(2026, 6, 8),
    )

    assert coverage.fresh == ("0005.HK",)
    assert coverage.stale == ("0700.HK",)
    assert coverage.no_history == ("9999.HK",)


def test_bootstrap_plan_uses_stale_top_up_and_full_bootstrap_for_no_history(universe_session):
    from app.services.price_refresh_planning import (
        NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
        STALE_PRICE_TOP_UP_PERIOD,
        plan_price_refresh,
    )

    universe_session.add(StockPrice(symbol="0700.HK", date=date(2026, 6, 5), close=100))
    universe_session.commit()

    github = _GithubService(
        {
            "status": "success",
            "as_of_date": "2026-06-05",
            "source_revision": "daily_prices_hk:20260605090000",
            "stale_reason": "behind expected session",
        }
    )

    plan = plan_price_refresh(
        universe_session,
        all_symbols=["0700.HK", "9999.HK"],
        mode="bootstrap",
        activity_lifecycle="bootstrap",
        effective_market="HK",
        price_bundle_service=github,
        market_calendar_service=_calendar(date(2026, 6, 8)),
    )

    assert plan.source == "github+live"
    assert plan.symbols == ("0700.HK", "9999.HK")
    assert [(job.kind, job.symbols, job.period) for job in plan.jobs] == [
        ("stale", ("0700.HK",), STALE_PRICE_TOP_UP_PERIOD),
        ("no_history", ("9999.HK",), NO_HISTORY_PRICE_BOOTSTRAP_PERIOD),
    ]
    assert github.sync_calls == [{"market": "HK", "allow_stale": True}]


def test_full_mode_stays_full_even_during_bootstrap_lifecycle(universe_session):
    from app.services.price_refresh_planning import (
        NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
        plan_price_refresh,
    )

    github = _GithubService({"status": "success", "as_of_date": "2026-06-08"})

    plan = plan_price_refresh(
        universe_session,
        all_symbols=["0700.HK", "9999.HK"],
        mode="full",
        activity_lifecycle="bootstrap",
        effective_market="HK",
        price_bundle_service=github,
        market_calendar_service=_calendar(date(2026, 6, 8)),
    )

    assert plan.source == "live"
    assert [(job.kind, job.symbols, job.period) for job in plan.jobs] == [
        ("full", ("0700.HK", "9999.HK"), NO_HISTORY_PRICE_BOOTSTRAP_PERIOD)
    ]
    assert github.sync_calls == []


def test_current_github_bundle_splits_only_missing_symbols_by_history(universe_session):
    from app.services.price_refresh_planning import (
        NO_HISTORY_PRICE_BOOTSTRAP_PERIOD,
        STALE_PRICE_TOP_UP_PERIOD,
        plan_price_refresh,
    )

    universe_session.add(StockPrice(symbol="0700.HK", date=date(2026, 6, 5), close=100))
    universe_session.commit()
    github = _GithubService(
        {
            "status": "success",
            "as_of_date": "2026-06-08",
            "source_revision": "daily_prices_hk:20260608090000",
        },
        missing_symbols=["0700.HK", "9999.HK"],
    )

    plan = plan_price_refresh(
        universe_session,
        all_symbols=["0700.HK", "0005.HK", "9999.HK"],
        mode="bootstrap",
        activity_lifecycle="bootstrap",
        effective_market="HK",
        price_bundle_service=github,
        market_calendar_service=_calendar(date(2026, 6, 8)),
    )

    assert plan.source == "github+live"
    assert [(job.kind, job.symbols, job.period) for job in plan.jobs] == [
        ("stale", ("0700.HK",), STALE_PRICE_TOP_UP_PERIOD),
        ("no_history", ("9999.HK",), NO_HISTORY_PRICE_BOOTSTRAP_PERIOD),
    ]
    assert github.missing_calls == [
        {"symbols": ["0700.HK", "0005.HK", "9999.HK"], "as_of_date": "2026-06-08"}
    ]


def test_current_github_bundle_accepts_datetime_as_of_date(universe_session):
    from app.services.price_refresh_planning import plan_price_refresh

    github = _GithubService(
        {
            "status": "success",
            "as_of_date": datetime(2026, 6, 8, 9, 0),
            "source_revision": "daily_prices_hk:20260608090000",
        },
        missing_symbols=[],
    )

    plan = plan_price_refresh(
        universe_session,
        all_symbols=["0700.HK"],
        mode="bootstrap",
        activity_lifecycle="bootstrap",
        effective_market="HK",
        price_bundle_service=github,
        market_calendar_service=_calendar(date(2026, 6, 8)),
    )

    assert plan.source == "github"
    assert plan.completion_message == "GitHub daily price bundle is current - no live fetch needed"
    assert github.missing_calls == [
        {"symbols": ["0700.HK"], "as_of_date": "2026-06-08"}
    ]
