from __future__ import annotations

from datetime import datetime


def test_price_refresh_outcome_serializes_typed_github_metadata():
    from app.services.price_refresh_planning import (
        GitHubSeedOutcome,
        PriceRefreshMode,
        PriceRefreshSource,
    )
    from app.services.price_refresh_workflow import PriceRefreshOutcome

    outcome = PriceRefreshOutcome(
        status="completed",
        mode=PriceRefreshMode.BOOTSTRAP,
        source=PriceRefreshSource.GITHUB,
        message="GitHub daily price bundle is current - no live fetch needed",
        refreshed=0,
        failed=0,
        total=0,
        completed_at=datetime(2026, 6, 8, 12, 0, 0),
        github_seed=GitHubSeedOutcome.from_mapping(
            {
                "status": "success",
                "as_of_date": "2026-06-08",
                "source_revision": "daily_prices_jp:20260608120000",
            }
        ),
    )

    assert outcome.to_task_result() == {
        "status": "completed",
        "source": "github",
        "github_sync_status": "success",
        "source_revision": "daily_prices_jp:20260608120000",
        "refreshed": 0,
        "failed": 0,
        "total": 0,
        "message": "GitHub daily price bundle is current - no live fetch needed",
        "mode": "bootstrap",
        "completed_at": "2026-06-08T12:00:00",
    }
