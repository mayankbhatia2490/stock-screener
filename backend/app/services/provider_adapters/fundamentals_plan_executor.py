"""Execute fundamentals provider plans through provider-specific adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from app.domain.providers.data_plan import (
    DATASET_FUNDAMENTALS,
    PROVIDER_AKSHARE,
    PROVIDER_BAOSTOCK,
    PROVIDER_FINVIZ,
    PROVIDER_KRX,
    PROVIDER_OPENDART,
    PROVIDER_YFINANCE,
    ProviderDataPlan,
    provider_data_plan_registry,
)
from app.services.security_master_service import SecurityIdentity, security_master_resolver

logger = logging.getLogger(__name__)

FundamentalsPlanResolver = Callable[[str | None, str | None], ProviderDataPlan]
SINGLE_SYMBOL_FUNDAMENTALS_PROVIDERS = frozenset({PROVIDER_AKSHARE, PROVIDER_KRX})


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

    def _get_eps_rating_data(self, symbol: str) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True, slots=True)
class _FundamentalsExecutionContext:
    plan: ProviderDataPlan
    identity: SecurityIdentity | None = None


def _default_plan_resolver(
    market: str | None,
    mic: str | None = None,
) -> ProviderDataPlan:
    return provider_data_plan_registry.plan_for(market, DATASET_FUNDAMENTALS, mic=mic)


def resolve_fundamentals_plan_for_symbol(
    symbol: str,
    market: str | None,
    *,
    plan_resolver: FundamentalsPlanResolver | None = None,
) -> ProviderDataPlan:
    """Resolve a fundamentals plan, including symbol-specific MIC overrides."""
    resolver = plan_resolver or _default_plan_resolver
    base_plan = resolver(market, None)
    if not base_plan.providers:
        return base_plan
    try:
        identity = security_master_resolver.resolve_identity(
            symbol=symbol,
            market=base_plan.market,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Could not resolve fundamentals plan identity for %s: %s", symbol, exc)
        return base_plan
    if identity.mic:
        return resolver(identity.market, identity.mic)
    return base_plan


def fundamentals_plan_uses_single_symbol_route(plan: ProviderDataPlan) -> bool:
    """Return whether a plan starts with a native single-symbol provider."""
    return bool(plan.providers and plan.providers[0] in SINGLE_SYMBOL_FUNDAMENTALS_PROVIDERS)


class FundamentalsProviderPlanExecutor:
    """Run fundamentals fetches according to ``ProviderDataPlanRegistry``."""

    def __init__(
        self,
        host: FundamentalsProviderHost,
        *,
        plan_resolver: FundamentalsPlanResolver | None = None,
    ) -> None:
        self._host = host
        self._plan_resolver = plan_resolver or _default_plan_resolver

    def fetch_fundamentals(
        self,
        symbol: str,
        *,
        market: str | None = None,
    ) -> dict[str, Any] | None:
        context = self._resolve_context(symbol, market)
        plan = context.plan
        if not plan.providers:
            logger.error(
                "No fundamentals provider plan for %s market=%r dataset=%s",
                symbol,
                market,
                DATASET_FUNDAMENTALS,
            )
            return None

        self._record_finviz_policy_exclusion(plan, market)
        if fundamentals_plan_uses_single_symbol_route(plan):
            if plan.providers[0] in {PROVIDER_AKSHARE, PROVIDER_BAOSTOCK}:
                return self._fetch_cn_fundamentals(symbol, context=context)
            if plan.providers[0] == PROVIDER_KRX:
                return self._fetch_kr_fundamentals(symbol, context=context)

        return self._fetch_generic_fundamentals(symbol, market=market, plan=plan)

    def fetch_combined_data(
        self,
        symbol: str,
        *,
        market: str | None = None,
    ) -> dict[str, Any] | None:
        context = self._resolve_context(symbol, market)
        plan = context.plan
        if not plan.providers:
            logger.error(
                "No fundamentals provider plan for %s market=%r dataset=%s",
                symbol,
                market,
                DATASET_FUNDAMENTALS,
            )
            return None

        if fundamentals_plan_uses_single_symbol_route(plan):
            if plan.providers[0] in {PROVIDER_AKSHARE, PROVIDER_BAOSTOCK}:
                return self._fetch_cn_combined(symbol, context=context)
            if plan.providers[0] == PROVIDER_KRX:
                return self._fetch_kr_combined(symbol, context=context)

        return self._fetch_generic_combined(symbol, market=market, plan=plan)

    def _resolve_context(
        self,
        symbol: str,
        market: str | None,
    ) -> _FundamentalsExecutionContext:
        base_plan = self._resolve_plan(market)
        if not base_plan.providers:
            return _FundamentalsExecutionContext(plan=base_plan)
        identity = self._resolve_identity(symbol, base_plan.market)
        if identity and identity.mic:
            return _FundamentalsExecutionContext(
                plan=self._resolve_plan(identity.market, identity.mic),
                identity=identity,
            )
        return _FundamentalsExecutionContext(plan=base_plan, identity=identity)

    def _resolve_plan(self, market: str | None, mic: str | None = None) -> ProviderDataPlan:
        return self._plan_resolver(market, mic)

    @staticmethod
    def _resolve_identity(symbol: str, market: str) -> SecurityIdentity | None:
        try:
            return security_master_resolver.resolve_identity(symbol=symbol, market=market)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.debug("Could not resolve fundamentals identity for %s: %s", symbol, exc)
            return None

    def _fetch_generic_fundamentals(
        self,
        symbol: str,
        *,
        market: str | None,
        plan: ProviderDataPlan,
    ) -> dict[str, Any] | None:
        finviz_failed = False
        for step in plan.steps:
            provider = step.provider
            if provider == PROVIDER_FINVIZ:
                if not self._finviz_allowed(plan):
                    continue
                logger.debug("Attempting to fetch %s fundamentals from finvizfinance", symbol)
                finviz_data = self._host.finviz_service.get_fundamentals(symbol)
                if finviz_data:
                    is_valid, errors = self._host.validator.validate_fundamentals(finviz_data)
                    if not is_valid:
                        logger.warning(
                            "Range validation warnings for %s fundamentals: %s",
                            symbol,
                            errors,
                        )

                    self._metric_inc("finviz_success")
                    logger.info("Using finvizfinance data for %s fundamentals", symbol)
                    finviz_data["data_source"] = PROVIDER_FINVIZ
                    finviz_data["data_source_timestamp"] = datetime.utcnow()
                    self._attach_provider_plan(finviz_data, plan)

                    eps_data = self._host._get_eps_rating_data(symbol)
                    if eps_data:
                        finviz_data.update(eps_data)
                        logger.debug(
                            "Supplemented finviz data with EPS rating data for %s",
                            symbol,
                        )
                    return finviz_data

                self._metric_inc("finviz_failed")
                logger.warning("finvizfinance failed to fetch %s", symbol)
                if not self._host.enable_fallback:
                    return None
                finviz_failed = True
                continue

            if provider == PROVIDER_YFINANCE:
                if finviz_failed:
                    logger.info("Falling back to yfinance for %s fundamentals", symbol)
                    self._metric_inc("yfinance_fallback")
                else:
                    logger.debug("Using yfinance as primary source for %s", symbol)
                    self._metric_inc("yfinance_primary")
                yf_data = self._host.yfinance_service.get_fundamentals(symbol)
                if yf_data:
                    yf_data["data_source"] = PROVIDER_YFINANCE
                    yf_data["data_source_timestamp"] = datetime.utcnow()
                    self._attach_provider_plan(yf_data, plan)
                    logger.info("Using yfinance data for %s fundamentals", symbol)
                    return yf_data
                continue

            self._log_unsupported_provider(provider, plan)

        logger.error("All data sources failed for %s fundamentals", symbol)
        return None

    def _fetch_cn_fundamentals(
        self,
        symbol: str,
        *,
        context: _FundamentalsExecutionContext,
    ) -> dict[str, Any] | None:
        plan = context.plan
        identity = context.identity or self._resolve_identity(symbol, plan.market)
        local_code = str(getattr(identity, "local_code", None) or symbol).split(".", 1)[0]
        canonical_symbol = getattr(identity, "canonical_symbol", symbol)
        merged: dict[str, Any] = {}
        sources: list[str] = []

        for step in plan.steps:
            provider = step.provider
            if provider == PROVIDER_AKSHARE:
                try:
                    core_data = self._host.cn_market_data_service.core_fundamentals(local_code)
                except Exception as exc:  # pragma: no cover - provider/network variability
                    logger.warning("AKShare CN core fundamentals failed for %s: %s", symbol, exc)
                    core_data = {}
                if core_data:
                    merged.update(core_data)
                    sources.append(PROVIDER_AKSHARE)
                continue

            if provider == PROVIDER_BAOSTOCK:
                try:
                    statement_data = self._host.cn_market_data_service.statement_fundamentals(
                        local_code
                    )
                except Exception as exc:  # pragma: no cover - provider/network variability
                    logger.warning("CN statement fundamentals failed for %s: %s", symbol, exc)
                    statement_data = {}
                if statement_data:
                    merged.update(
                        {key: value for key, value in statement_data.items() if value is not None}
                    )
                    sources.append("cn_statement")
                continue

            if provider == PROVIDER_YFINANCE:
                if not self._host.enable_fallback:
                    continue
                yf_data = self._host.yfinance_service.get_fundamentals(canonical_symbol)
                if yf_data:
                    for key, value in yf_data.items():
                        if value is not None and key not in merged:
                            merged[key] = value
                    sources.append(PROVIDER_YFINANCE)
                continue

            self._log_unsupported_provider(provider, plan)

        if not merged:
            logger.error("All CN data sources failed for %s fundamentals", symbol)
            return None

        merged["symbol"] = canonical_symbol
        merged["market"] = "CN"
        merged["currency"] = getattr(identity, "currency", "CNY")
        merged["data_source"] = "+".join(dict.fromkeys(sources)) or "cn"
        merged["data_source_timestamp"] = datetime.utcnow()
        if getattr(identity, "mic", None) == "XBSE":
            merged["yfinance_status"] = "disabled_for_beijing"
        self._attach_provider_plan(merged, plan)
        return merged

    def _fetch_kr_fundamentals(
        self,
        symbol: str,
        *,
        context: _FundamentalsExecutionContext,
    ) -> dict[str, Any] | None:
        plan = context.plan
        identity = context.identity or self._resolve_identity(symbol, plan.market)
        local_code = str(getattr(identity, "local_code", None) or symbol).split(".", 1)[0]
        canonical_symbol = getattr(identity, "canonical_symbol", symbol)
        merged: dict[str, Any] = {}
        sources: list[str] = []

        for step in plan.steps:
            provider = step.provider
            if provider == PROVIDER_KRX:
                try:
                    krx_data = self._host.krx_fundamentals_service.core_fundamentals(local_code)
                except Exception as exc:  # pragma: no cover - provider/network variability
                    logger.warning("KRX fundamentals failed for %s: %s", symbol, exc)
                    krx_data = {}
                if krx_data:
                    merged.update(krx_data)
                    sources.append(PROVIDER_KRX)
                continue

            if provider == PROVIDER_OPENDART:
                try:
                    dart_data = (
                        self._host.opendart_fundamentals_service.get_statement_fundamentals(
                            local_code
                        )
                    )
                except Exception as exc:  # pragma: no cover - provider/network variability
                    logger.warning("OpenDART fundamentals failed for %s: %s", symbol, exc)
                    dart_data = {}
                if dart_data:
                    merged.update(
                        {key: value for key, value in dart_data.items() if value is not None}
                    )
                    sources.append(PROVIDER_OPENDART)
                continue

            if provider == PROVIDER_YFINANCE:
                if not self._host.enable_fallback:
                    continue
                yf_data = self._host.yfinance_service.get_fundamentals(canonical_symbol)
                if yf_data:
                    for key, value in yf_data.items():
                        if value is not None and key not in merged:
                            merged[key] = value
                    sources.append(PROVIDER_YFINANCE)
                continue

            self._log_unsupported_provider(provider, plan)

        if not merged:
            logger.error("All KR data sources failed for %s fundamentals", symbol)
            return None

        merged["symbol"] = canonical_symbol
        merged["market"] = "KR"
        merged["currency"] = getattr(identity, "currency", "KRW")
        merged["data_source"] = "+".join(dict.fromkeys(sources)) or "kr"
        merged["data_source_timestamp"] = datetime.utcnow()
        if (
            plan.allows(PROVIDER_OPENDART)
            and not self._host.opendart_fundamentals_service.is_configured
        ):
            merged["opendart_status"] = "missing_api_key"
        self._attach_provider_plan(merged, plan)
        return merged

    def _fetch_generic_combined(
        self,
        symbol: str,
        *,
        market: str | None,
        plan: ProviderDataPlan,
    ) -> dict[str, Any] | None:
        self._record_finviz_policy_exclusion(plan, market)
        if self._finviz_allowed(plan):
            logger.debug("Attempting to fetch %s combined data from finvizfinance", symbol)
            combined_data = self._host.finviz_service.get_combined_data(
                symbol,
                validate=self._host.strict_validation,
            )
            if combined_data:
                self._metric_inc("finviz_success")
                logger.info("Using finvizfinance for %s combined data", symbol)
                timestamp = datetime.utcnow()
                combined_data["fundamentals"]["data_source"] = PROVIDER_FINVIZ
                combined_data["fundamentals"]["data_source_timestamp"] = timestamp
                self._attach_provider_plan(combined_data["fundamentals"], plan)
                combined_data["growth"]["data_source"] = PROVIDER_FINVIZ
                combined_data["growth"]["data_source_timestamp"] = timestamp
                return combined_data

            self._metric_inc("finviz_failed")
            logger.warning("finvizfinance failed for %s combined data", symbol)
            if not self._host.enable_fallback:
                return None
            logger.info("Falling back to yfinance for %s combined data", symbol)
            self._metric_inc("yfinance_fallback")
        else:
            logger.debug("Using yfinance as primary source for %s", symbol)
            self._metric_inc("yfinance_primary")

        if not plan.allows(PROVIDER_YFINANCE):
            logger.error("No yfinance fallback in provider plan for %s combined data", symbol)
            return None

        fundamentals = self._host.yfinance_service.get_fundamentals(symbol)
        growth = self._host.yfinance_service.get_quarterly_growth(symbol, market=market)
        if fundamentals and growth:
            timestamp = datetime.utcnow()
            fundamentals["data_source"] = PROVIDER_YFINANCE
            fundamentals["data_source_timestamp"] = timestamp
            self._attach_provider_plan(fundamentals, plan)
            growth["data_source"] = PROVIDER_YFINANCE
            growth["data_source_timestamp"] = timestamp
            logger.info("Using yfinance for %s combined data", symbol)
            return {
                "fundamentals": fundamentals,
                "growth": growth,
                "data_source": PROVIDER_YFINANCE,
            }

        logger.error("All data sources failed for %s combined data", symbol)
        return None

    def _fetch_cn_combined(
        self,
        symbol: str,
        *,
        context: _FundamentalsExecutionContext,
    ) -> dict[str, Any] | None:
        fundamentals = self._fetch_cn_fundamentals(symbol, context=context)
        identity = context.identity or self._resolve_identity(symbol, context.plan.market)
        growth: dict[str, Any] = {}
        if context.plan.allows(PROVIDER_YFINANCE):
            growth = self._host.yfinance_service.get_quarterly_growth(
                getattr(identity, "canonical_symbol", symbol),
                market="CN",
            ) or {}
        if fundamentals:
            timestamp = datetime.utcnow()
            if growth:
                growth["data_source"] = PROVIDER_YFINANCE
                growth["data_source_timestamp"] = timestamp
            return {
                "fundamentals": fundamentals,
                "growth": growth,
                "data_source": fundamentals.get("data_source", "cn"),
            }
        logger.error("All CN data sources failed for %s combined data", symbol)
        return None

    def _fetch_kr_combined(
        self,
        symbol: str,
        *,
        context: _FundamentalsExecutionContext,
    ) -> dict[str, Any] | None:
        fundamentals = self._fetch_kr_fundamentals(symbol, context=context)
        identity = context.identity or self._resolve_identity(symbol, context.plan.market)
        growth = None
        if context.plan.allows(PROVIDER_YFINANCE):
            growth = self._host.yfinance_service.get_quarterly_growth(
                getattr(identity, "canonical_symbol", symbol),
                market="KR",
            )
        if fundamentals:
            timestamp = datetime.utcnow()
            if growth:
                growth["data_source"] = PROVIDER_YFINANCE
                growth["data_source_timestamp"] = timestamp
            return {
                "fundamentals": fundamentals,
                "growth": growth or {},
                "data_source": fundamentals.get("data_source", "krx"),
            }
        logger.error("All KR data sources failed for %s combined data", symbol)
        return None

    def _finviz_allowed(self, plan: ProviderDataPlan) -> bool:
        return bool(self._host.prefer_finviz and plan.allows(PROVIDER_FINVIZ))

    def _record_finviz_policy_exclusion(
        self,
        plan: ProviderDataPlan,
        requested_market: str | None,
    ) -> None:
        if not self._host.prefer_finviz or plan.allows(PROVIDER_FINVIZ):
            return
        self._metric_inc("finviz_skipped_by_policy")
        logger.debug(
            "Provider data plan %s excluded finviz for market=%r resolved_market=%s",
            plan.version,
            requested_market,
            plan.market,
        )

    def _metric_inc(self, key: str) -> None:
        self._host.metrics[key] = self._host.metrics.get(key, 0) + 1

    @staticmethod
    def _attach_provider_plan(payload: dict[str, Any] | None, plan: ProviderDataPlan) -> None:
        if payload is not None:
            payload["provider_data_plan"] = plan.provenance_metadata()

    @staticmethod
    def _log_unsupported_provider(provider: str, plan: ProviderDataPlan) -> None:
        logger.warning(
            "Unsupported fundamentals provider %r in plan %s/%s version %s",
            provider,
            plan.market,
            plan.dataset,
            plan.version,
        )
