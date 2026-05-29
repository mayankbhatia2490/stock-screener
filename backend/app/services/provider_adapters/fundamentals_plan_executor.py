"""Execute fundamentals provider plans through provider-specific adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from app.domain.providers.data_plan import (
    DATASET_FUNDAMENTALS,
    PROVIDER_FINVIZ,
    PROVIDER_YFINANCE,
    ProviderDataPlan,
    provider_data_plan_registry,
)
from app.services.security_master_service import SecurityIdentity, security_master_resolver

from .fundamentals_provider_adapters import (
    DEFAULT_FUNDAMENTALS_ADAPTER_CAPABILITIES,
    FundamentalsExecutionContext,
    FundamentalsProviderAdapter,
    FundamentalsProviderHost,
    default_fundamentals_provider_adapters,
)

logger = logging.getLogger(__name__)

FundamentalsPlanResolver = Callable[[str | None, str | None], ProviderDataPlan]


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
    identity = _resolve_identity(symbol, base_plan.market)
    if identity and identity.mic:
        return resolver(identity.market, identity.mic)
    return base_plan


def fundamentals_plan_requires_single_symbol_route(
    plan: ProviderDataPlan,
    *,
    provider_adapters: Mapping[str, FundamentalsProviderAdapter] | None = None,
) -> bool:
    """Return whether a plan contains providers that cannot use batch yfinance routing."""
    for step in plan.steps:
        if provider_adapters is not None:
            adapter = provider_adapters.get(step.provider)
            if adapter is not None and adapter.requires_single_symbol_route:
                return True
            continue
        if DEFAULT_FUNDAMENTALS_ADAPTER_CAPABILITIES.get(step.provider, False):
            return True
    return False


class FundamentalsProviderPlanExecutor:
    """Run fundamentals fetches according to ``ProviderDataPlanRegistry``."""

    def __init__(
        self,
        host: FundamentalsProviderHost,
        *,
        plan_resolver: FundamentalsPlanResolver | None = None,
        provider_adapters: Mapping[str, FundamentalsProviderAdapter] | None = None,
    ) -> None:
        self._host = host
        self._plan_resolver = plan_resolver or _default_plan_resolver
        self._provider_adapters = (
            dict(provider_adapters)
            if provider_adapters is not None
            else default_fundamentals_provider_adapters(host)
        )

    def fetch_fundamentals(
        self,
        symbol: str,
        *,
        market: str | None = None,
    ) -> dict[str, Any] | None:
        context = self._resolve_context(symbol, market)
        if not context.plan.providers:
            self._log_empty_plan(symbol, market)
            return None

        self._record_finviz_policy_exclusion(context.plan, market)
        return self._execute_fundamentals_plan(
            context,
            merge_all_steps=self._requires_single_symbol_route(context.plan),
        )

    def fetch_combined_data(
        self,
        symbol: str,
        *,
        market: str | None = None,
    ) -> dict[str, Any] | None:
        context = self._resolve_context(symbol, market)
        if not context.plan.providers:
            self._log_empty_plan(symbol, market)
            return None

        if self._requires_single_symbol_route(context.plan):
            fundamentals = self._execute_fundamentals_plan(context, merge_all_steps=True)
            return self._combined_from_fundamentals(context, fundamentals)

        return self._fetch_generic_combined(context)

    def _resolve_context(
        self,
        symbol: str,
        market: str | None,
    ) -> FundamentalsExecutionContext:
        base_plan = self._resolve_plan(market)
        if not base_plan.providers:
            return FundamentalsExecutionContext(
                symbol=symbol,
                requested_market=market,
                plan=base_plan,
            )
        identity = _resolve_identity(symbol, base_plan.market)
        plan = (
            self._resolve_plan(identity.market, identity.mic)
            if identity and identity.mic
            else base_plan
        )
        return FundamentalsExecutionContext(
            symbol=symbol,
            requested_market=market,
            plan=plan,
            identity=identity,
        )

    def _resolve_plan(self, market: str | None, mic: str | None = None) -> ProviderDataPlan:
        return self._plan_resolver(market, mic)

    def _requires_single_symbol_route(self, plan: ProviderDataPlan) -> bool:
        return fundamentals_plan_requires_single_symbol_route(
            plan,
            provider_adapters=self._provider_adapters,
        )

    def _execute_fundamentals_plan(
        self,
        context: FundamentalsExecutionContext,
        *,
        merge_all_steps: bool,
    ) -> dict[str, Any] | None:
        merged: dict[str, Any] = {}
        sources: list[str] = []
        metadata: dict[str, Any] = {}
        fallback_active = False

        for step in context.plan.steps:
            adapter = self._provider_adapters.get(step.provider)
            if adapter is None:
                self._log_unsupported_provider(step.provider, context.plan)
                continue

            step_context = replace(
                context,
                fallback_active=fallback_active,
                allow_fallback_provider=self._host.enable_fallback or not merge_all_steps,
                record_yfinance_metrics=not merge_all_steps,
                use_canonical_provider_symbol=merge_all_steps,
            )
            result = adapter.fetch(step_context)
            metadata.update(result.metadata)

            if result.payload:
                if not merge_all_steps:
                    payload = dict(result.payload)
                    self._finalize_payload(
                        payload,
                        plan=context.plan,
                        source_label=result.source_label or result.provider,
                    )
                    return payload

                self._merge_payload(
                    merged,
                    result.payload,
                    missing_only=result.merge_missing_only,
                )
                if result.source_label:
                    sources.append(result.source_label)

            if result.activate_fallback:
                fallback_active = True
            if result.stop_plan:
                return None

        if not merged:
            logger.error("All data sources failed for %s fundamentals", context.symbol)
            return None

        self._finalize_merged_payload(
            merged,
            context=context,
            sources=sources,
            metadata=metadata,
        )
        return merged

    def _fetch_generic_combined(
        self,
        context: FundamentalsExecutionContext,
    ) -> dict[str, Any] | None:
        plan = context.plan
        self._record_finviz_policy_exclusion(plan, context.requested_market)
        if self._finviz_allowed(plan):
            logger.debug(
                "Attempting to fetch %s combined data from finvizfinance",
                context.symbol,
            )
            combined_data = self._host.finviz_service.get_combined_data(
                context.symbol,
                validate=self._host.strict_validation,
            )
            if combined_data:
                self._metric_inc("finviz_success")
                logger.info("Using finvizfinance for %s combined data", context.symbol)
                timestamp = datetime.utcnow()
                fundamentals = combined_data["fundamentals"]
                fundamentals["data_source"] = PROVIDER_FINVIZ
                fundamentals["data_source_timestamp"] = timestamp
                fundamentals["provider_data_plan"] = plan.provenance_metadata()
                combined_data["growth"]["data_source"] = PROVIDER_FINVIZ
                combined_data["growth"]["data_source_timestamp"] = timestamp
                return combined_data

            self._metric_inc("finviz_failed")
            logger.warning("finvizfinance failed for %s combined data", context.symbol)
            if not self._host.enable_fallback:
                return None
            logger.info("Falling back to yfinance for %s combined data", context.symbol)
            self._metric_inc("yfinance_fallback")
        else:
            logger.debug("Using yfinance as primary source for %s", context.symbol)
            self._metric_inc("yfinance_primary")

        if not plan.allows(PROVIDER_YFINANCE):
            logger.error("No yfinance fallback in provider plan for %s combined data", context.symbol)
            return None

        fundamentals = self._host.yfinance_service.get_fundamentals(context.symbol)
        growth = self._host.yfinance_service.get_quarterly_growth(
            context.symbol,
            market=context.requested_market,
        )
        if fundamentals and growth:
            timestamp = datetime.utcnow()
            fundamentals["data_source"] = PROVIDER_YFINANCE
            fundamentals["data_source_timestamp"] = timestamp
            fundamentals["provider_data_plan"] = plan.provenance_metadata()
            growth["data_source"] = PROVIDER_YFINANCE
            growth["data_source_timestamp"] = timestamp
            logger.info("Using yfinance for %s combined data", context.symbol)
            return {
                "fundamentals": fundamentals,
                "growth": growth,
                "data_source": PROVIDER_YFINANCE,
            }

        logger.error("All data sources failed for %s combined data", context.symbol)
        return None

    def _combined_from_fundamentals(
        self,
        context: FundamentalsExecutionContext,
        fundamentals: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not fundamentals:
            logger.error(
                "All %s data sources failed for %s combined data",
                context.plan.market,
                context.symbol,
            )
            return None

        growth: dict[str, Any] = {}
        if context.plan.allows(PROVIDER_YFINANCE):
            growth = self._host.yfinance_service.get_quarterly_growth(
                context.canonical_symbol,
                market=context.plan.market,
            ) or {}
        if growth:
            growth["data_source"] = PROVIDER_YFINANCE
            growth["data_source_timestamp"] = datetime.utcnow()
        return {
            "fundamentals": fundamentals,
            "growth": growth,
            "data_source": fundamentals.get("data_source", context.plan.market.lower()),
        }

    @staticmethod
    def _merge_payload(
        target: dict[str, Any],
        payload: dict[str, Any],
        *,
        missing_only: bool,
    ) -> None:
        for key, value in payload.items():
            if value is None:
                continue
            if missing_only and key in target:
                continue
            target[key] = value

    @staticmethod
    def _finalize_payload(
        payload: dict[str, Any],
        *,
        plan: ProviderDataPlan,
        source_label: str,
    ) -> None:
        payload["data_source"] = source_label
        payload["data_source_timestamp"] = datetime.utcnow()
        payload["provider_data_plan"] = plan.provenance_metadata()

    def _finalize_merged_payload(
        self,
        payload: dict[str, Any],
        *,
        context: FundamentalsExecutionContext,
        sources: list[str],
        metadata: dict[str, Any],
    ) -> None:
        payload.update(metadata)
        payload["symbol"] = context.canonical_symbol
        payload["market"] = context.plan.market
        payload["currency"] = context.currency
        payload["data_source"] = (
            "+".join(dict.fromkeys(sources)) or context.plan.market.lower()
        )
        payload["data_source_timestamp"] = datetime.utcnow()
        if getattr(context.identity, "mic", None) == "XBSE":
            payload["yfinance_status"] = "disabled_for_beijing"
        payload["provider_data_plan"] = context.plan.provenance_metadata()

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
    def _log_empty_plan(symbol: str, market: str | None) -> None:
        logger.error(
            "No fundamentals provider plan for %s market=%r dataset=%s",
            symbol,
            market,
            DATASET_FUNDAMENTALS,
        )

    @staticmethod
    def _log_unsupported_provider(provider: str, plan: ProviderDataPlan) -> None:
        logger.warning(
            "Unsupported fundamentals provider %r in plan %s/%s version %s",
            provider,
            plan.market,
            plan.dataset,
            plan.version,
        )


def _resolve_identity(symbol: str, market: str) -> SecurityIdentity | None:
    try:
        return security_master_resolver.resolve_identity(symbol=symbol, market=market)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.debug("Could not resolve fundamentals identity for %s: %s", symbol, exc)
        return None
