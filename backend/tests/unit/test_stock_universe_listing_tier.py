from __future__ import annotations

from app.models.stock_universe import (
    UNIVERSE_EVENT_LISTING_TIER_CHANGED,
    UNIVERSE_EVENT_STATUS_CHANGED,
    UNIVERSE_STATUS_ACTIVE,
    StockUniverse,
    StockUniverseStatusEvent,
)
from app.services.stock_universe_service import StockUniverseService


def test_stock_universe_listing_tier_is_nullable_row_metadata() -> None:
    row = StockUniverse(symbol="0700.HK", market="HK")

    assert row.listing_tier is None

    row.listing_tier = "main_board"

    assert row.listing_tier == "main_board"


def test_status_event_defaults_to_status_changed_event_type() -> None:
    event = StockUniverseService._build_status_event_record(
        symbol="0700.HK",
        old_status=None,
        new_status="active",
        trigger_source="test",
        reason="created",
    )

    assert event.event_type == UNIVERSE_EVENT_STATUS_CHANGED


def test_status_event_can_record_listing_tier_change_without_status_transition() -> None:
    assert StockUniverseStatusEvent.new_status.property.columns[0].nullable is True

    event = StockUniverseService._build_metadata_event_record(
        symbol="0700.HK",
        event_type=UNIVERSE_EVENT_LISTING_TIER_CHANGED,
        trigger_source="test",
        reason="listing tier changed",
        payload={"previous": None, "current": "main_board"},
    )

    assert event.event_type == "listing_tier_changed"
    assert event.old_status is None
    assert event.new_status is None


def test_get_active_symbols_can_filter_by_listing_tier(db_session) -> None:
    db_session.add_all(
        [
            StockUniverse(
                symbol="0005.HK",
                market="HK",
                exchange="XHKG",
                listing_tier="main_board",
                market_cap=100,
                is_active=True,
                status=UNIVERSE_STATUS_ACTIVE,
            ),
            StockUniverse(
                symbol="0800.HK",
                market="HK",
                exchange="XHKG",
                listing_tier="gem",
                market_cap=90,
                is_active=True,
                status=UNIVERSE_STATUS_ACTIVE,
            ),
        ]
    )
    db_session.commit()

    symbols = StockUniverseService().get_active_symbols(
        db_session,
        market="HK",
        listing_tier="gem",
    )

    assert symbols == ["0800.HK"]
