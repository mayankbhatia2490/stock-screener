from __future__ import annotations

from app.domain.providers.data_plan import (
    DATASET_FUNDAMENTALS,
    PLAN_VERSION,
    ProviderDataPlanRegistry,
    ProviderPlanStep,
    provider_data_plan_registry,
)
from app.services.provider_routing_policy import (
    PROVIDER_ALPHAVANTAGE,
    PROVIDER_FINVIZ,
    PROVIDER_YFINANCE,
)


def test_default_fundamentals_plan_preserves_us_provider_order() -> None:
    plan = provider_data_plan_registry.plan_for("US", DATASET_FUNDAMENTALS)

    assert plan.market == "US"
    assert plan.dataset == DATASET_FUNDAMENTALS
    assert plan.mic is None
    assert plan.version == PLAN_VERSION
    assert plan.providers == (
        PROVIDER_FINVIZ,
        PROVIDER_YFINANCE,
        PROVIDER_ALPHAVANTAGE,
    )
    assert plan.step_for(PROVIDER_YFINANCE).batch_size == 50


def test_default_fundamentals_plan_records_provenance_metadata() -> None:
    metadata = provider_data_plan_registry.plan_for("HK", DATASET_FUNDAMENTALS).provenance_metadata()

    assert metadata == {
        "version": PLAN_VERSION,
        "dataset": DATASET_FUNDAMENTALS,
        "market": "HK",
        "mic": None,
        "providers": [PROVIDER_YFINANCE],
    }


def test_registry_applies_market_mic_dataset_override() -> None:
    registry = ProviderDataPlanRegistry(
        plans={
            ("US", DATASET_FUNDAMENTALS): (
                ProviderPlanStep(PROVIDER_FINVIZ, batch_size=None),
            ),
        },
        overrides={
            ("US", "XNAS", DATASET_FUNDAMENTALS): (
                ProviderPlanStep(PROVIDER_YFINANCE, batch_size=25),
            ),
        },
        version="test-plan",
    )

    base = registry.plan_for("US", DATASET_FUNDAMENTALS)
    override = registry.plan_for("us", DATASET_FUNDAMENTALS, mic="xnas")

    assert base.providers == (PROVIDER_FINVIZ,)
    assert base.mic is None
    assert override.providers == (PROVIDER_YFINANCE,)
    assert override.mic == "XNAS"
    assert override.version == "test-plan"
    assert override.step_for(PROVIDER_YFINANCE).batch_size == 25


def test_unknown_market_fails_closed_with_empty_plan() -> None:
    plan = provider_data_plan_registry.plan_for("XX", DATASET_FUNDAMENTALS)

    assert plan.market == "XX"
    assert plan.providers == ()
