from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.stock_universe import StockUniverse, UNIVERSE_STATUS_ACTIVE
from app.services.universe_row_facts import (
    UniverseRowFacts,
    UniverseRowFactsResolver,
    active_universe_currency_drift,
    active_universe_timezone_drift,
)


def _make_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return factory


def _add_universe_row(
    db,
    *,
    symbol: str,
    market: str,
    exchange: str,
    currency: str,
    timezone: str,
) -> None:
    db.add(
        StockUniverse(
            symbol=symbol,
            market=market,
            exchange=exchange,
            currency=currency,
            timezone=timezone,
            is_active=True,
            status=UNIVERSE_STATUS_ACTIVE,
        )
    )


def test_resolver_returns_normalized_market_and_currency_from_universe_row():
    factory = _make_session_factory()
    db = factory()
    _add_universe_row(
        db,
        symbol="0700.HK",
        market=" hk ",
        exchange="XHKG",
        currency=" hkd ",
        timezone="Asia/Hong_Kong",
    )
    db.commit()
    db.close()

    resolver = UniverseRowFactsResolver(factory)

    assert resolver.resolve("0700.HK") == UniverseRowFacts(
        market="HK",
        currency="HKD",
    )


def test_payload_facts_use_payload_currency_before_universe_row_fallback():
    factory = _make_session_factory()
    db = factory()
    _add_universe_row(
        db,
        symbol="SAP.DE",
        market="DE",
        exchange="XETR",
        currency="EUR",
        timezone="Europe/Berlin",
    )
    db.commit()
    db.close()

    resolver = UniverseRowFactsResolver(factory)

    assert resolver.resolve_for_payload(
        "SAP.DE",
        {"currency": "NOK"},
        market="DE",
    ) == UniverseRowFacts(market="DE", currency="NOK")


def test_active_universe_drift_helpers_report_currency_and_timezone_mismatch():
    factory = _make_session_factory()
    db = factory()
    _add_universe_row(
        db,
        symbol="BAD.HK",
        market="HK",
        exchange="XHKG",
        currency="EUR",
        timezone="Asia/Hong_Kong",
    )
    _add_universe_row(
        db,
        symbol="BAD.SI",
        market="SG",
        exchange="XSES",
        currency="SGD",
        timezone="Asia/Hong_Kong",
    )
    db.commit()

    assert active_universe_currency_drift(db) == [
        {
            "symbol": "BAD.HK",
            "market": "HK",
            "currency": "EUR",
            "supported_currencies": ("HKD",),
        }
    ]
    assert active_universe_timezone_drift(db) == [
        {
            "symbol": "BAD.SI",
            "market": "SG",
            "mic": "XSES",
            "timezone": "Asia/Hong_Kong",
            "expected_timezone": "Asia/Singapore",
        }
    ]
    db.close()
