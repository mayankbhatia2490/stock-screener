from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.providers.data_plan import (
    DATASET_FUNDAMENTALS,
    PROVIDER_FINVIZ,
    PROVIDER_KRX,
    PROVIDER_OPENDART,
    PROVIDER_YFINANCE,
    ProviderDataPlan,
    ProviderPlanStep,
)
from app.services.provider_adapters.fundamentals_plan_executor import (
    FundamentalsProviderPlanExecutor,
    fundamentals_plan_requires_single_symbol_route,
)
from app.services.provider_adapters.fundamentals_provider_adapters import (
    FundamentalsExecutionContext,
    ProviderExecutionResult,
)


class _FakeOpenDart:
    is_configured = True

    def __init__(self, statement_fields=None):
        self.statement_fields = statement_fields or {}
        self.calls = []

    def get_statement_fundamentals(self, local_code):
        self.calls.append(local_code)
        return dict(self.statement_fields)


class _FakeHost:
    def __init__(self) -> None:
        self.prefer_finviz = True
        self.enable_fallback = True
        self.strict_validation = True
        self.metrics = {
            "finviz_success": 0,
            "finviz_failed": 0,
            "yfinance_fallback": 0,
            "yfinance_primary": 0,
            "total_calls": 0,
            "finviz_skipped_by_policy": 0,
        }
        self.validator = MagicMock()
        self.validator.validate_fundamentals.return_value = (True, [])
        self.finviz_service = MagicMock()
        self.yfinance_service = MagicMock()
        self.cn_market_data_service = MagicMock()
        self.krx_fundamentals_service = MagicMock()
        self.opendart_fundamentals_service = _FakeOpenDart()
        self.eps_rating_calls = []

    def get_eps_rating_data(self, symbol: str):
        self.eps_rating_calls.append(symbol)
        return {"eps_raw_score": 87}


def test_executor_routes_us_finviz_first_and_attaches_plan_metadata() -> None:
    host = _FakeHost()
    host.finviz_service.get_fundamentals.return_value = {"market_cap": 2_000}
    plan = ProviderDataPlan(
        market="US",
        dataset=DATASET_FUNDAMENTALS,
        steps=(
            ProviderPlanStep(PROVIDER_FINVIZ, batch_size=1, fallback=False),
            ProviderPlanStep(PROVIDER_YFINANCE, batch_size=50),
        ),
        version="test-plan",
    )
    executor = FundamentalsProviderPlanExecutor(
        host,
        plan_resolver=lambda market, mic=None: plan,
    )

    result = executor.fetch_fundamentals("AAPL", market="US")

    host.finviz_service.get_fundamentals.assert_called_once_with("AAPL")
    host.yfinance_service.get_fundamentals.assert_not_called()
    assert host.eps_rating_calls == ["AAPL"]
    assert result["data_source"] == "finviz"
    assert result["eps_raw_score"] == 87
    assert result["provider_data_plan"] == plan.provenance_metadata()
    assert host.metrics["finviz_success"] == 1


def test_executor_uses_security_master_mic_override_for_cn_bjse_fallback() -> None:
    host = _FakeHost()
    host.cn_market_data_service.core_fundamentals.return_value = {"market_cap": 1_000}
    host.cn_market_data_service.statement_fundamentals.return_value = {
        "revenue_current": 10_000,
    }
    executor = FundamentalsProviderPlanExecutor(host)

    result = executor.fetch_fundamentals("920118.BJ", market="CN")

    host.cn_market_data_service.core_fundamentals.assert_called_once_with("920118")
    host.cn_market_data_service.statement_fundamentals.assert_called_once_with("920118")
    host.yfinance_service.get_fundamentals.assert_not_called()
    assert result["data_source"] == "akshare+cn_statement"
    assert result["yfinance_status"] == "disabled_for_beijing"
    assert result["provider_data_plan"]["mic"] == "XBSE"
    assert result["provider_data_plan"]["providers"] == ["akshare", "baostock"]


def test_executor_merges_krx_opendart_and_yfinance_by_plan_order() -> None:
    host = _FakeHost()
    host.krx_fundamentals_service.core_fundamentals.return_value = {
        "market_cap": 1_000,
        "pe_ratio": 9.5,
    }
    host.opendart_fundamentals_service = _FakeOpenDart({"revenue_current": 10_000})
    host.yfinance_service.get_fundamentals.return_value = {
        "market_cap": 2_000,
        "dividend_yield": 0.02,
    }
    plan = ProviderDataPlan(
        market="KR",
        dataset=DATASET_FUNDAMENTALS,
        steps=(
            ProviderPlanStep(PROVIDER_KRX, batch_size=200, fallback=False),
            ProviderPlanStep(PROVIDER_OPENDART, batch_size=100),
            ProviderPlanStep(PROVIDER_YFINANCE, batch_size=50),
        ),
        version="test-plan",
    )
    executor = FundamentalsProviderPlanExecutor(
        host,
        plan_resolver=lambda market, mic=None: plan,
    )

    result = executor.fetch_fundamentals("005930.KS", market="KR")

    host.krx_fundamentals_service.core_fundamentals.assert_called_once_with("005930")
    assert host.opendart_fundamentals_service.calls == ["005930"]
    host.yfinance_service.get_fundamentals.assert_called_once_with("005930.KS")
    assert result["market_cap"] == 1_000
    assert result["dividend_yield"] == 0.02
    assert result["data_source"] == "krx+opendart+yfinance"
    assert result["provider_data_plan"] == plan.provenance_metadata()


def test_executor_fails_closed_when_plan_has_no_executable_provider() -> None:
    host = _FakeHost()
    plan = ProviderDataPlan(
        market="US",
        dataset=DATASET_FUNDAMENTALS,
        steps=(ProviderPlanStep("unsupported-provider", batch_size=1),),
        version="test-plan",
    )
    executor = FundamentalsProviderPlanExecutor(
        host,
        plan_resolver=lambda market, mic=None: plan,
    )

    result = executor.fetch_fundamentals("AAPL", market="US")

    host.finviz_service.get_fundamentals.assert_not_called()
    host.yfinance_service.get_fundamentals.assert_not_called()
    assert result is None


class _StaticAdapter:
    def __init__(
        self,
        provider: str,
        payload: dict,
        *,
        requires_single_symbol_route: bool = False,
        merge_missing_only: bool = False,
    ) -> None:
        self.provider = provider
        self.payload = payload
        self.requires_single_symbol_route = requires_single_symbol_route
        self.merge_missing_only = merge_missing_only
        self.calls: list[FundamentalsExecutionContext] = []

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        self.calls.append(context)
        return ProviderExecutionResult(
            provider=self.provider,
            payload=dict(self.payload),
            source_label=self.provider,
            merge_missing_only=self.merge_missing_only,
        )


def test_executor_dispatches_native_steps_through_registered_adapters() -> None:
    host = _FakeHost()
    first = _StaticAdapter(
        "native-core",
        {"market_cap": 1_000, "pe_ratio": 10.0},
        requires_single_symbol_route=True,
    )
    second = _StaticAdapter(
        "native-supplement",
        {"market_cap": 2_000, "revenue_current": 50_000},
        requires_single_symbol_route=True,
        merge_missing_only=True,
    )
    plan = ProviderDataPlan(
        market="US",
        dataset=DATASET_FUNDAMENTALS,
        steps=(
            ProviderPlanStep("native-core", batch_size=1, fallback=False),
            ProviderPlanStep("native-supplement", batch_size=1),
        ),
        version="test-plan",
    )
    adapters = {
        "native-core": first,
        "native-supplement": second,
    }
    executor = FundamentalsProviderPlanExecutor(
        host,
        plan_resolver=lambda market, mic=None: plan,
        provider_adapters=adapters,
    )

    assert fundamentals_plan_requires_single_symbol_route(plan, provider_adapters=adapters)
    result = executor.fetch_fundamentals("AAPL", market="US")

    assert [call.symbol for call in first.calls] == ["AAPL"]
    assert [call.symbol for call in second.calls] == ["AAPL"]
    assert result["market_cap"] == 1_000
    assert result["revenue_current"] == 50_000
    assert result["data_source"] == "native-core+native-supplement"
    assert result["provider_data_plan"] == plan.provenance_metadata()
