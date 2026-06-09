"""Bootstrap price-cache readiness over the canonical price-refresh universe."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.domain.markets.catalog import get_market_catalog
from app.services.bootstrap_cache_coverage import evaluate_bootstrap_price_cache_coverage
from app.services.price_refresh_plan_builder import load_active_price_refresh_universe
from app.services.price_symbol_validation import split_supported_price_symbols


def _normalize_market(market: str | None) -> str:
    return get_market_catalog().get(market or "US").code


def load_bootstrap_price_symbols(
    db: Session,
    *,
    market: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return provider-eligible price symbols from the price-refresh universe."""
    market_code = _normalize_market(market)
    universe = load_active_price_refresh_universe(
        db,
        market=market_code,
        effective_market=market_code,
        normalize_market=_normalize_market,
    )
    supported_symbols, unsupported_symbols = split_supported_price_symbols(
        list(universe.symbols)
    )
    return tuple(supported_symbols), tuple(unsupported_symbols)


def evaluate_bootstrap_price_readiness(
    db: Session,
    *,
    market: str,
    as_of_date: date,
) -> dict[str, Any]:
    """Evaluate bootstrap price coverage using the same universe as price refresh."""
    market_code = _normalize_market(market)
    supported_symbols, unsupported_symbols = load_bootstrap_price_symbols(
        db,
        market=market_code,
    )
    report = evaluate_bootstrap_price_cache_coverage(
        db,
        market=market_code,
        symbols=supported_symbols,
        as_of_date=as_of_date,
    )
    return {
        **report,
        "unsupported_skipped_count": len(unsupported_symbols),
        "unsupported_symbols_preview": list(unsupported_symbols[:20]),
    }
