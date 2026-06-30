from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.stock import StockPrice
from app.models.stock_universe import StockUniverse, UNIVERSE_STATUS_ACTIVE


def make_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def stock_row(symbol: str, market: str, exchange: str, market_cap: float) -> StockUniverse:
    return StockUniverse(
        symbol=symbol,
        market=market,
        exchange=exchange,
        is_active=True,
        status=UNIVERSE_STATUS_ACTIVE,
        status_reason="active",
        market_cap=market_cap,
    )


def price_row(symbol: str, day: date, close: float) -> StockPrice:
    return StockPrice(
        symbol=symbol,
        date=day,
        open=close - 1,
        high=close + 1,
        low=close - 2,
        close=close,
        adj_close=close - 0.5,
        volume=1_000_000,
    )


def bundle_price(
    *,
    day: str = "2026-04-18",
    open_price: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.5,
) -> dict[str, object]:
    return {
        "date": day,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "adj_close": close,
        "volume": 1_000_000,
    }
