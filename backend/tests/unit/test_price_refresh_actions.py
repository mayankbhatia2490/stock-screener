from __future__ import annotations

import pytest


def _preparation(*, refresh_plan, all_symbols=None, symbols=None):
    from app.services.price_refresh_actions import PriceRefreshPreparation

    return PriceRefreshPreparation(
        all_symbols=list(all_symbols or []),
        symbol_markets={},
        github_seed=refresh_plan.github_seed,
        refresh_plan=refresh_plan,
        refresh_source=refresh_plan.source,
        symbols=list(symbols if symbols is not None else refresh_plan.symbols),
        live_refresh_jobs=list(refresh_plan.jobs),
    )


def test_price_refresh_action_requires_live_fetch_when_plan_has_symbols():
    from app.services.price_refresh_actions import PriceRefreshActionFactory
    from app.services.price_refresh_planning import PriceRefreshMode, PriceRefreshPlan

    factory = PriceRefreshActionFactory(
        last_completed_trading_day=lambda market: pytest.fail(
            f"unexpected calendar lookup for {market}"
        )
    )

    action = factory.build(
        mode=PriceRefreshMode.BOOTSTRAP,
        effective_market="JP",
        preparation=_preparation(
            refresh_plan=PriceRefreshPlan(symbols=("7203.T",)),
        ),
    )

    assert action.requires_live_fetch is True
    assert action.terminal_completion is None


def test_price_refresh_action_builds_github_terminal_completion():
    from datetime import date

    from app.services.price_refresh_actions import PriceRefreshActionFactory
    from app.services.price_refresh_planning import (
        GitHubSeedOutcome,
        PriceRefreshMode,
        PriceRefreshPlan,
        PriceRefreshSource,
    )

    github_seed = GitHubSeedOutcome.from_mapping(
        {
            "status": "success",
            "as_of_date": "2026-06-08",
            "source_revision": "daily_prices_jp:20260608120000",
        }
    )
    assert github_seed is not None
    plan = PriceRefreshPlan(
        symbols=(),
        github_seed=github_seed,
        github_seed_used=True,
        completion_message="GitHub daily price bundle is current - no live fetch needed",
    )
    factory = PriceRefreshActionFactory(
        last_completed_trading_day=lambda market: date(2026, 6, 7)
    )

    action = factory.build(
        mode=PriceRefreshMode.BOOTSTRAP,
        effective_market="JP",
        preparation=_preparation(
            refresh_plan=plan,
            all_symbols=["7203.T", "9984.T"],
        ),
    )

    assert action.requires_live_fetch is False
    assert action.terminal_completion is not None
    completion = action.terminal_completion
    assert completion.outcome.source is PriceRefreshSource.GITHUB
    assert completion.outcome.github_seed is github_seed
    assert completion.outcome.message == plan.completion_message
    assert completion.finalization.metadata_refreshed == 2
    assert completion.finalization.metadata_total == 2
    assert completion.finalization.market_success_rates == {
        "JP": (date(2026, 6, 8), 1.0),
    }
