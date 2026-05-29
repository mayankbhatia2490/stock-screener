"""Provider-specific fundamentals adapters used by provider data plans."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.providers.data_plan import (
    PROVIDER_AKSHARE,
    PROVIDER_BAOSTOCK,
    PROVIDER_FINVIZ,
    PROVIDER_KRX,
    PROVIDER_OPENDART,
    PROVIDER_YFINANCE,
    ProviderDataPlan,
)
from app.services.security_master_service import SecurityIdentity

logger = logging.getLogger(__name__)


class FundamentalsProviderHost(Protocol):
    prefer_finviz: bool
    enable_fallback: bool
    strict_validation: bool
    metrics: dict[str, int]
    validator: Any
    finviz_service: Any
    yfinance_service: Any
    cn_market_data_service: Any
    krx_fundamentals_service: Any
    opendart_fundamentals_service: Any

    def get_eps_rating_data(self, symbol: str) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True, slots=True)
class FundamentalsExecutionContext:
    symbol: str
    requested_market: str | None
    plan: ProviderDataPlan
    identity: SecurityIdentity | None = None
    fallback_active: bool = False
    allow_fallback_provider: bool = True
    record_yfinance_metrics: bool = True
    use_canonical_provider_symbol: bool = False

    @property
    def canonical_symbol(self) -> str:
        return getattr(self.identity, "canonical_symbol", self.symbol)

    @property
    def provider_symbol(self) -> str:
        if self.use_canonical_provider_symbol:
            return self.canonical_symbol
        return self.symbol

    @property
    def local_code(self) -> str:
        return str(getattr(self.identity, "local_code", None) or self.symbol).split(".", 1)[0]

    @property
    def market(self) -> str:
        return str(getattr(self.identity, "market", None) or self.plan.market)

    @property
    def currency(self) -> str:
        return str(getattr(self.identity, "currency", None) or "")


@dataclass(frozen=True, slots=True)
class ProviderExecutionResult:
    provider: str
    payload: dict[str, Any] | None = None
    source_label: str | None = None
    merge_missing_only: bool = False
    activate_fallback: bool = False
    stop_plan: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class FundamentalsProviderAdapter(Protocol):
    provider: str
    requires_single_symbol_route: bool
    merge_missing_only: bool

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        ...


def _metric_inc(host: FundamentalsProviderHost, key: str) -> None:
    host.metrics[key] = host.metrics.get(key, 0) + 1


class FinvizFundamentalsAdapter:
    provider = PROVIDER_FINVIZ
    requires_single_symbol_route = False
    merge_missing_only = False

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        if not self._host.prefer_finviz:
            return ProviderExecutionResult(provider=self.provider)

        logger.debug("Attempting to fetch %s fundamentals from finvizfinance", context.symbol)
        finviz_data = self._host.finviz_service.get_fundamentals(context.symbol)
        if not finviz_data:
            _metric_inc(self._host, "finviz_failed")
            logger.warning("finvizfinance failed to fetch %s", context.symbol)
            return ProviderExecutionResult(
                provider=self.provider,
                activate_fallback=self._host.enable_fallback,
                stop_plan=not self._host.enable_fallback,
            )

        is_valid, errors = self._host.validator.validate_fundamentals(finviz_data)
        if not is_valid:
            logger.warning(
                "Range validation warnings for %s fundamentals: %s",
                context.symbol,
                errors,
            )

        _metric_inc(self._host, "finviz_success")
        logger.info("Using finvizfinance data for %s fundamentals", context.symbol)
        eps_data = self._host.get_eps_rating_data(context.symbol)
        if eps_data:
            finviz_data.update(eps_data)
            logger.debug("Supplemented finviz data with EPS rating data for %s", context.symbol)
        return ProviderExecutionResult(
            provider=self.provider,
            payload=finviz_data,
            source_label=PROVIDER_FINVIZ,
        )


class YFinanceFundamentalsAdapter:
    provider = PROVIDER_YFINANCE
    requires_single_symbol_route = False
    merge_missing_only = True

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        if not context.allow_fallback_provider:
            return ProviderExecutionResult(provider=self.provider)

        if context.record_yfinance_metrics:
            if context.fallback_active:
                logger.info("Falling back to yfinance for %s fundamentals", context.symbol)
                _metric_inc(self._host, "yfinance_fallback")
            else:
                logger.debug("Using yfinance as primary source for %s", context.symbol)
                _metric_inc(self._host, "yfinance_primary")

        yf_data = self._host.yfinance_service.get_fundamentals(context.provider_symbol)
        if not yf_data:
            return ProviderExecutionResult(provider=self.provider)

        logger.info("Using yfinance data for %s fundamentals", context.symbol)
        return ProviderExecutionResult(
            provider=self.provider,
            payload=yf_data,
            source_label=PROVIDER_YFINANCE,
            merge_missing_only=self.merge_missing_only,
        )


class AkshareFundamentalsAdapter:
    provider = PROVIDER_AKSHARE
    requires_single_symbol_route = True
    merge_missing_only = False

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        try:
            core_data = self._host.cn_market_data_service.core_fundamentals(
                context.local_code
            )
        except Exception as exc:  # pragma: no cover - provider/network variability
            logger.warning("AKShare CN core fundamentals failed for %s: %s", context.symbol, exc)
            core_data = {}
        return ProviderExecutionResult(
            provider=self.provider,
            payload=core_data or None,
            source_label=PROVIDER_AKSHARE if core_data else None,
        )


class BaostockFundamentalsAdapter:
    provider = PROVIDER_BAOSTOCK
    requires_single_symbol_route = True
    merge_missing_only = False

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        try:
            statement_data = self._host.cn_market_data_service.statement_fundamentals(
                context.local_code
            )
        except Exception as exc:  # pragma: no cover - provider/network variability
            logger.warning("CN statement fundamentals failed for %s: %s", context.symbol, exc)
            statement_data = {}
        payload = {
            key: value for key, value in (statement_data or {}).items() if value is not None
        }
        return ProviderExecutionResult(
            provider=self.provider,
            payload=payload or None,
            source_label="cn_statement" if payload else None,
        )


class KrxFundamentalsAdapter:
    provider = PROVIDER_KRX
    requires_single_symbol_route = True
    merge_missing_only = False

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        try:
            krx_data = self._host.krx_fundamentals_service.core_fundamentals(
                context.local_code
            )
        except Exception as exc:  # pragma: no cover - provider/network variability
            logger.warning("KRX fundamentals failed for %s: %s", context.symbol, exc)
            krx_data = {}
        return ProviderExecutionResult(
            provider=self.provider,
            payload=krx_data or None,
            source_label=PROVIDER_KRX if krx_data else None,
        )


class OpenDartFundamentalsAdapter:
    provider = PROVIDER_OPENDART
    requires_single_symbol_route = True
    merge_missing_only = False

    def __init__(self, host: FundamentalsProviderHost) -> None:
        self._host = host

    def fetch(self, context: FundamentalsExecutionContext) -> ProviderExecutionResult:
        metadata: dict[str, Any] = {}
        if not self._host.opendart_fundamentals_service.is_configured:
            metadata["opendart_status"] = "missing_api_key"

        try:
            dart_data = self._host.opendart_fundamentals_service.get_statement_fundamentals(
                context.local_code
            )
        except Exception as exc:  # pragma: no cover - provider/network variability
            logger.warning("OpenDART fundamentals failed for %s: %s", context.symbol, exc)
            dart_data = {}
        payload = {key: value for key, value in (dart_data or {}).items() if value is not None}
        return ProviderExecutionResult(
            provider=self.provider,
            payload=payload or None,
            source_label=PROVIDER_OPENDART if payload else None,
            metadata=metadata,
        )


DEFAULT_FUNDAMENTALS_ADAPTER_CAPABILITIES: dict[str, bool] = {
    PROVIDER_FINVIZ: False,
    PROVIDER_YFINANCE: False,
    PROVIDER_AKSHARE: True,
    PROVIDER_BAOSTOCK: True,
    PROVIDER_KRX: True,
    PROVIDER_OPENDART: True,
}


def default_fundamentals_provider_adapters(
    host: FundamentalsProviderHost,
) -> dict[str, FundamentalsProviderAdapter]:
    adapters: list[FundamentalsProviderAdapter] = [
        FinvizFundamentalsAdapter(host),
        YFinanceFundamentalsAdapter(host),
        AkshareFundamentalsAdapter(host),
        BaostockFundamentalsAdapter(host),
        KrxFundamentalsAdapter(host),
        OpenDartFundamentalsAdapter(host),
    ]
    return {adapter.provider: adapter for adapter in adapters}
