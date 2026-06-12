"""Aggregated Daily Snapshot payload for server mode.

Mirrors the static-site ``home.json`` bundle so the Daily Snapshot tab renders
from a single request (key-market cards, top scan candidates, leaders in
leading groups, top groups, freshness dates) instead of ~14 round-trips.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.domain.common.query import FilterSpec, PageSpec, QuerySpec, SortOrder, SortSpec
from app.domain.markets.key_markets import key_market_instruments
from app.models.market_breadth import MarketBreadth
from app.models.scan_result import Scan
from app.models.stock import StockPrice
from app.schemas.scanning import ScanResultItem
from app.use_cases.scanning.get_scan_results import GetScanResultsQuery

logger = logging.getLogger(__name__)

DAILY_SNAPSHOT_SCHEMA_VERSION = 1
DAILY_SNAPSHOT_CACHE_TTL_SECONDS = 600
DAILY_SNAPSHOT_TOP_RESULTS = 20
KEY_MARKET_HISTORY_POINTS = 30
# Calendar window wide enough to cover 30 trading days across holidays.
KEY_MARKET_HISTORY_CALENDAR_DAYS = 60
LEADERS_MAX_GROUP_RANK = 40
LEADERS_MIN_RS_RATING = 80
TOP_GROUPS_LIMIT = 10


def daily_snapshot_cache_key(market: str) -> str:
    return f"daily_snapshot:v{DAILY_SNAPSHOT_SCHEMA_VERSION}:{market.upper()}"


def daily_snapshot_etag(payload_json: str) -> str:
    return 'W/"{}"'.format(hashlib.sha1(payload_json.encode("utf-8")).hexdigest())


def _default_min_dollar_volume(market: str) -> int | None:
    from app.services.static_site_export_service import StaticSiteExportService

    return StaticSiteExportService.resolve_static_default_filters(market).get("minVolume")


def _latest_completed_scan(db: Session, market: str) -> Scan | None:
    return (
        db.query(Scan)
        .filter(
            Scan.status == "completed",
            Scan.universe_market == market,
        )
        .order_by(Scan.completed_at.desc().nullslast(), Scan.id.desc())
        .first()
    )


def _scan_freshness(scan: Scan | None) -> dict[str, Any]:
    if scan is None:
        return {
            "scan_id": None,
            "scan_as_of_date": None,
            "scan_published_at": None,
        }
    run = scan.feature_run
    as_of = run.as_of_date.isoformat() if run is not None and run.as_of_date else None
    if as_of is None and scan.completed_at is not None:
        as_of = scan.completed_at.date().isoformat()
    published_at = None
    if run is not None and run.published_at is not None:
        published_at = run.published_at.isoformat()
    elif scan.completed_at is not None:
        published_at = scan.completed_at.isoformat()
    return {
        "scan_id": scan.scan_id,
        "scan_as_of_date": as_of,
        "scan_published_at": published_at,
    }


def _build_key_markets(db: Session, market: str) -> list[dict[str, Any]]:
    instruments = key_market_instruments(market)
    if not instruments:
        return []
    data_symbols = [instrument.data_symbol for instrument in instruments]
    cutoff = date.today() - timedelta(days=KEY_MARKET_HISTORY_CALENDAR_DAYS)
    rows = (
        db.query(StockPrice.symbol, StockPrice.date, StockPrice.close)
        .filter(
            StockPrice.symbol.in_(data_symbols),
            StockPrice.date >= cutoff,
        )
        .order_by(StockPrice.symbol.asc(), StockPrice.date.asc())
        .all()
    )
    history_by_symbol: dict[str, list[tuple[date, float | None]]] = defaultdict(list)
    for symbol, row_date, close in rows:
        history_by_symbol[str(symbol).upper()].append((row_date, close))

    entries: list[dict[str, Any]] = []
    for instrument in instruments:
        points = [
            {"date": row_date.isoformat(), "close": close}
            for row_date, close in history_by_symbol.get(instrument.data_symbol.upper(), [])
            if close is not None
        ][-KEY_MARKET_HISTORY_POINTS:]
        latest = points[-1] if points else None
        previous = points[-2] if len(points) > 1 else None
        change_1d = None
        if latest is not None and previous is not None and previous["close"] not in (None, 0):
            change_1d = round(
                ((latest["close"] - previous["close"]) / previous["close"]) * 100, 2
            )
        entries.append(
            {
                "symbol": instrument.display_symbol,
                "display_name": instrument.display_name,
                "currency": instrument.currency,
                "latest_close": latest["close"] if latest is not None else None,
                "latest_date": latest["date"] if latest is not None else None,
                "change_1d": change_1d,
                "history": points,
            }
        )
    return entries


def _query_scan_rows(
    *,
    uow: Any,
    use_case: Any,
    scan_id: str,
    filters: FilterSpec,
) -> list[dict[str, Any]]:
    query = GetScanResultsQuery(
        scan_id=scan_id,
        query_spec=QuerySpec(
            filters=filters,
            sort=SortSpec(field="composite_score", order=SortOrder.DESC),
            page=PageSpec(page=1, per_page=DAILY_SNAPSHOT_TOP_RESULTS),
        ),
        include_sparklines=True,
        include_setup_payload=False,
    )
    result = use_case.execute(uow, query)
    return [
        ScanResultItem.from_domain(item, include_setup_payload=False).model_dump(mode="json")
        for item in result.page.items
    ]


def _build_top_groups(db: Session, market: str) -> tuple[list[dict[str, Any]], str | None]:
    from app.wiring.bootstrap import get_group_rank_service

    try:
        rankings = get_group_rank_service().get_current_rankings(
            db, limit=TOP_GROUPS_LIMIT, market=market
        )
    except Exception:  # groups are optional for markets without rankings
        logger.info("Daily snapshot: no group rankings for market %s", market)
        return [], None
    if not rankings:
        return [], None
    groups_date = rankings[0].get("date")
    keep = (
        "industry_group",
        "rank",
        "rank_change_1w",
        "rank_change_1m",
        "top_symbol",
        "top_symbol_name",
        "top_rs_rating",
    )
    return [{key: row.get(key) for key in keep} for row in rankings], groups_date


def _latest_breadth_date(db: Session, market: str) -> str | None:
    latest = (
        db.query(MarketBreadth.date)
        .filter(MarketBreadth.market == market)
        .order_by(MarketBreadth.date.desc())
        .first()
    )
    if latest is None or latest[0] is None:
        return None
    value = latest[0]
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def build_daily_snapshot_payload(
    db: Session,
    *,
    market: str,
    market_display_name: str,
    uow: Any,
    scan_results_use_case: Any,
) -> dict[str, Any]:
    """Assemble the full Daily Snapshot payload for one market."""
    normalized = market.upper()
    scan = _latest_completed_scan(db, normalized)
    min_volume = _default_min_dollar_volume(normalized)

    top_candidates: list[dict[str, Any]] = []
    leaders: list[dict[str, Any]] = []
    if scan is not None:
        candidate_filters = FilterSpec()
        candidate_filters.add_range("volume", min_volume, None)
        top_candidates = _query_scan_rows(
            uow=uow,
            use_case=scan_results_use_case,
            scan_id=scan.scan_id,
            filters=candidate_filters,
        )

        leader_filters = FilterSpec()
        leader_filters.add_range("volume", min_volume, None)
        leader_filters.add_range("rs_rating", LEADERS_MIN_RS_RATING, None)
        leader_filters.add_range("ibd_group_rank", None, LEADERS_MAX_GROUP_RANK)
        leaders = _query_scan_rows(
            uow=uow,
            use_case=scan_results_use_case,
            scan_id=scan.scan_id,
            filters=leader_filters,
        )

    top_groups, groups_date = _build_top_groups(db, normalized)
    freshness = _scan_freshness(scan)
    freshness["breadth_latest_date"] = _latest_breadth_date(db, normalized)
    freshness["groups_latest_date"] = groups_date

    return {
        "schema_version": DAILY_SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": normalized,
        "market_display_name": market_display_name,
        "scan_id": freshness["scan_id"],
        "freshness": freshness,
        "key_markets": _build_key_markets(db, normalized),
        "top_candidates": {
            "min_dollar_volume": min_volume,
            "rows": top_candidates,
        },
        "leaders": {
            "criteria": {
                "max_group_rank": LEADERS_MAX_GROUP_RANK,
                "min_rs_rating": LEADERS_MIN_RS_RATING,
                "min_dollar_volume": min_volume,
            },
            "rows": leaders,
        },
        "top_groups": top_groups,
    }
