"""Application workflow for smart market price refreshes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Any, Protocol

from celery.exceptions import SoftTimeLimitExceeded

from ..config import settings
from ..services.price_refresh_execution import run_price_refresh_jobs
from ..services.price_refresh_planning import (
    GitHubSeedOutcome,
    LIVE_TOP_UP_MODES,
    PriceRefreshMode,
    PriceRefreshPlan,
    PriceRefreshSource,
)

logger = logging.getLogger(__name__)


class CeleryTaskLike(Protocol):
    name: str
    request: Any

    def update_state(self, *args, **kwargs) -> None:
        ...


@dataclass(frozen=True)
class PriceRefreshOutcome:
    status: str
    mode: PriceRefreshMode
    source: PriceRefreshSource
    message: str | None = None
    refreshed: int = 0
    failed: int = 0
    total: int = 0
    failed_symbols: list[str] = field(default_factory=list)
    completed_at: datetime = field(default_factory=datetime.now)
    github_seed: GitHubSeedOutcome | None = None

    def to_task_result(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "source": self.source.value,
            "refreshed": self.refreshed,
            "failed": self.failed,
            "total": self.total,
            "mode": self.mode.value,
            "completed_at": self.completed_at.isoformat(),
        }
        if self.github_seed is not None:
            result["github_sync_status"] = self.github_seed.status_value
            result["source_revision"] = self.github_seed.source_revision
        if self.message is not None:
            result["message"] = self.message
        if self.failed_symbols:
            result["failed_symbols"] = self.failed_symbols[:20]
        return result


@dataclass(frozen=True)
class PriceRefreshFinalization:
    metadata_status: str
    metadata_refreshed: int
    metadata_total: int
    activity_current: int
    activity_total: int
    message: str
    heartbeat_status: str | None = "completed"
    market_success_rates: Mapping[str, tuple[Any, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceRefreshWorkflowDependencies:
    session_factory: Callable[[], Any]
    price_cache_factory: Callable[[], Any]
    bulk_fetcher_factory: Callable[[], Any]
    warm_benchmarks: Callable[..., Mapping[str, Any]]
    plan_price_refresh: Callable[..., PriceRefreshPlan]
    fetch_with_backoff: Callable[..., Mapping[str, Mapping[str, Any]]]
    track_symbol_failures: Callable[..., None]
    schedule_failed_symbol_retry: Callable[..., None]
    record_market_refresh_success: Callable[..., None]
    mark_market_activity_started: Callable[..., None]
    mark_market_activity_completed: Callable[..., None]
    mark_market_activity_progress_safely: Callable[..., None]
    mark_market_activity_failed_safely: Callable[..., None]
    daily_price_bundle_service_factory: Callable[[], Any]
    market_calendar_service_factory: Callable[[], Any]
    rate_limiter_factory: Callable[[], Any]
    normalize_market: Callable[[str], str]
    market_tag: Callable[[str | None], str]
    log_extra: Callable[[str | None], Mapping[str, Any]]
    get_eastern_now: Callable[[], Any]
    is_trading_day: Callable[[Any], bool]
    format_market_status: Callable[[], str]
    is_market_enabled_now: Callable[[str], bool]
    raise_if_transient_database_error: Callable[[Exception], None]
    safe_rollback: Callable[[Any], None]
    time_window_bypass_enabled: Callable[[], bool] = lambda: False


@dataclass
class LivePriceRefreshExecutionContext:
    task: CeleryTaskLike
    bulk_fetcher: Any
    price_cache: Any
    db: Any
    market: str | None
    effective_market: str
    activity_lifecycle: str
    symbol_markets: dict[str, str]
    dependencies: PriceRefreshWorkflowDependencies
    processed: int = 0

    def market_for_symbol(self, symbol: str) -> str:
        return self.symbol_markets.get(str(symbol).upper(), self.effective_market)

    def fetch_batch(self, symbols: Sequence[str], *, period: str, market: str | None):
        return self.dependencies.fetch_with_backoff(
            self.bulk_fetcher,
            list(symbols),
            period=period,
            market=market,
        )

    def store_prices(self, price_data_by_symbol: Mapping[str, Any]) -> None:
        self.price_cache.store_batch_in_cache(
            dict(price_data_by_symbol),
            also_store_db=True,
        )

    def track_symbol_failures(
        self,
        successes: Sequence[str],
        failures: Sequence[str],
        *,
        failure_details: Mapping[str, str],
    ) -> None:
        self.dependencies.track_symbol_failures(
            self.price_cache,
            list(successes),
            list(failures),
            self.db,
            failure_details=dict(failure_details),
        )

    def publish_progress(
        self,
        current: int,
        total: int,
        percent: float,
        message: str,
        *,
        refreshed: int,
        failed: int,
    ) -> None:
        self.processed = current
        self.task.update_state(
            state="PROGRESS",
            meta={
                "current": current,
                "total": total,
                "percent": percent,
                "refreshed": refreshed,
                "failed": failed,
            },
        )
        self.price_cache.update_warmup_heartbeat(
            current,
            total,
            percent,
            market=self.market,
        )
        self.dependencies.mark_market_activity_progress_safely(
            self.db,
            market=self.effective_market,
            stage_key="prices",
            lifecycle=self.activity_lifecycle,
            task_name=getattr(self.task, "name", "smart_refresh_cache"),
            task_id=getattr(getattr(self.task, "request", None), "id", None),
            current=current,
            total=total,
            percent=round(percent, 1),
            message=message,
        )

    def extend_lock(self) -> None:
        task_id = getattr(getattr(self.task, "request", None), "id", None) or "unknown"
        from ..wiring.bootstrap import get_data_fetch_lock

        get_data_fetch_lock().extend_lock(task_id, 300, market=self.market)

    def wait_between_batches(self) -> None:
        rate_limiter = self.dependencies.rate_limiter_factory()
        if self.market is not None:
            rate_limiter.wait_for_market("yfinance:batch", self.market)
            return
        rate_limiter.wait(
            "yfinance:batch",
            min_interval_s=settings.yfinance_batch_rate_limit_interval,
        )

    def raise_if_transient_database_error(self, exc: Exception) -> None:
        self.dependencies.raise_if_transient_database_error(exc)


class PriceRefreshWorkflow:
    def __init__(self, dependencies: PriceRefreshWorkflowDependencies) -> None:
        self._deps = dependencies

    def run(
        self,
        *,
        task: CeleryTaskLike,
        mode: PriceRefreshMode | str = PriceRefreshMode.AUTO,
        market: str | None = None,
        activity_lifecycle: str | None = None,
    ) -> dict[str, Any]:
        parsed_mode = PriceRefreshMode.parse(mode)
        effective_market = (
            self._deps.normalize_market(market) if market is not None else "US"
        )
        activity_lifecycle = activity_lifecycle or "daily_refresh"
        log_extra = self._deps.log_extra(market)

        logger.info("=" * 80)
        logger.info(
            "TASK: Smart Cache Refresh %s (mode=%s)",
            self._deps.market_tag(market),
            parsed_mode.value,
            extra=log_extra,
        )
        logger.info("Market status: %s", self._deps.format_market_status(), extra=log_extra)
        logger.info("Timestamp: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), extra=log_extra)
        logger.info("=" * 80)

        if market is not None and not self._deps.is_market_enabled_now(
            self._deps.normalize_market(market)
        ):
            logger.info("Skipping smart refresh for disabled market %s", market, extra=log_extra)
            return {
                "status": "skipped",
                "reason": f"market {effective_market} is disabled in local runtime preferences",
                "market": effective_market,
                "mode": parsed_mode.value,
                "timestamp": datetime.now().isoformat(),
            }

        if self._should_reject_full_refresh(parsed_mode, task, market):
            now_et = self._deps.get_eastern_now()
            return {
                "skipped": True,
                "reason": f"Outside refresh window (weekday={now_et.weekday()}, hour={now_et.hour})",
                "mode": parsed_mode.value,
                "timestamp": datetime.now().isoformat(),
            }

        if parsed_mode is PriceRefreshMode.AUTO:
            today = self._deps.get_eastern_now().date()
            if not self._deps.is_trading_day(today):
                logger.info("Skipping smart refresh (auto) - %s is not a trading day", today)
                return {
                    "skipped": True,
                    "reason": "Not a trading day",
                    "date": today.isoformat(),
                    "mode": parsed_mode.value,
                }

        price_cache = self._deps.price_cache_factory()
        db = self._deps.session_factory()

        refreshed = 0
        processed = 0
        failed = 0
        github_seed: GitHubSeedOutcome | None = None
        execution_context: LivePriceRefreshExecutionContext | None = None

        try:
            self._deps.mark_market_activity_started(
                db,
                market=effective_market,
                stage_key="prices",
                lifecycle=activity_lifecycle,
                task_name=getattr(task, "name", "smart_refresh_cache"),
                task_id=getattr(getattr(task, "request", None), "id", None),
                message="Refreshing market prices",
            )

            logger.info("[1/3] Warming market benchmarks...")
            benchmark_result = self._deps.warm_benchmarks(market=market)
            if benchmark_result.get("error"):
                logger.error("Benchmark warmup failed: %s", benchmark_result.get("error"))

            logger.info("[2/3] Determining symbols to refresh (mode=%s)...", parsed_mode.value)
            all_symbols, symbol_markets = self._load_active_symbol_universe(
                db,
                market=market,
                effective_market=effective_market,
            )

            def symbols_needing_auto_refresh(candidate_symbols: Sequence[str]) -> Sequence[str]:
                logger.info(
                    "Auto refresh: %d active symbols (full universe, market cap order) %s",
                    len(candidate_symbols),
                    self._deps.market_tag(market),
                    extra=log_extra,
                )
                refresh_symbols = price_cache.get_symbols_needing_refresh(
                    list(candidate_symbols),
                    max_age_hours=settings.refresh_skip_hours,
                )
                skipped = len(candidate_symbols) - len(refresh_symbols)
                if skipped > 0:
                    logger.info(
                        "Skipping %d recently-refreshed symbols (fresh within %sh)",
                        skipped,
                        settings.refresh_skip_hours,
                    )
                return refresh_symbols

            if (
                parsed_mode in LIVE_TOP_UP_MODES
                and all_symbols
                and market is not None
            ):
                github_seed = GitHubSeedOutcome.from_mapping(
                    self._deps.daily_price_bundle_service_factory().sync_from_github(
                        db,
                        market=effective_market,
                        allow_stale=True,
                    )
                )

            refresh_plan = self._deps.plan_price_refresh(
                db,
                all_symbols=all_symbols,
                mode=parsed_mode,
                effective_market=effective_market,
                market_calendar_service=self._deps.market_calendar_service_factory(),
                github_sync=github_seed,
                recently_refreshed_filter=(
                    symbols_needing_auto_refresh
                    if parsed_mode is PriceRefreshMode.AUTO
                    else None
                ),
            )
            github_seed = self._github_seed_from_plan(refresh_plan)
            refresh_source = self._source_from_plan(refresh_plan)
            symbols = list(refresh_plan.symbols)
            live_refresh_jobs = list(refresh_plan.jobs)

            self._publish_github_seed_log(
                github_seed=github_seed,
                refresh_plan=refresh_plan,
                effective_market=effective_market,
                all_symbols=all_symbols,
                activity_lifecycle=activity_lifecycle,
                db=db,
                task=task,
                log_extra=log_extra,
            )
            self._log_live_symbol_plan(
                refresh_plan=refresh_plan,
                refresh_source=refresh_source,
                symbols=symbols,
                mode=parsed_mode,
                market=market,
                effective_market=effective_market,
                log_extra=log_extra,
            )

            if refresh_source is PriceRefreshSource.GITHUB and not symbols:
                message = (
                    refresh_plan.completion_message
                    or "GitHub daily price bundle is current - no live fetch needed"
                )
                trading_day = self._completion_trading_day(github_seed, effective_market)
                outcome = PriceRefreshOutcome(
                    status="completed",
                    source=PriceRefreshSource.GITHUB,
                    mode=parsed_mode,
                    message=message,
                    github_seed=github_seed,
                )
                finalization = PriceRefreshFinalization(
                    metadata_status="completed",
                    metadata_refreshed=len(all_symbols),
                    metadata_total=len(all_symbols),
                    activity_current=len(all_symbols) if all_symbols else 0,
                    activity_total=len(all_symbols) if all_symbols else 0,
                    message=message,
                    market_success_rates={effective_market: (trading_day, 1.0)},
                )
                self._finalize_success(
                    db,
                    price_cache,
                    task,
                    market=market,
                    effective_market=effective_market,
                    activity_lifecycle=activity_lifecycle,
                    finalization=finalization,
                )
                return outcome.to_task_result()

            if not symbols:
                message = self._empty_refresh_message(refresh_plan, parsed_mode)
                outcome = PriceRefreshOutcome(
                    status="completed",
                    source=refresh_source,
                    mode=parsed_mode,
                    message=message,
                    github_seed=github_seed,
                )
                finalization = PriceRefreshFinalization(
                    metadata_status="completed",
                    metadata_refreshed=0,
                    metadata_total=0,
                    activity_current=0,
                    activity_total=0,
                    message=message,
                    heartbeat_status=None,
                )
                self._finalize_success(
                    db,
                    price_cache,
                    task,
                    market=market,
                    effective_market=effective_market,
                    activity_lifecycle=activity_lifecycle,
                    finalization=finalization,
                )
                return outcome.to_task_result()

            total = len(symbols)
            symbol_market_totals = Counter(
                symbol_markets.get(str(symbol).upper(), effective_market)
                for symbol in symbols
            )
            bulk_fetcher = self._deps.bulk_fetcher_factory()
            execution_context = LivePriceRefreshExecutionContext(
                task=task,
                bulk_fetcher=bulk_fetcher,
                price_cache=price_cache,
                db=db,
                market=market,
                effective_market=effective_market,
                activity_lifecycle=activity_lifecycle,
                symbol_markets=symbol_markets,
                dependencies=self._deps,
            )

            price_cache.update_warmup_heartbeat(0, total, 0.0, market=market)
            self._deps.mark_market_activity_progress_safely(
                db,
                market=effective_market,
                stage_key="prices",
                lifecycle=activity_lifecycle,
                task_name=getattr(task, "name", "smart_refresh_cache"),
                task_id=getattr(getattr(task, "request", None), "id", None),
                current=0,
                total=total,
                percent=0,
                message="Refreshing market prices",
            )

            logger.info("[3/3] Fetching %d symbols...", total)
            execution_result = run_price_refresh_jobs(
                jobs=live_refresh_jobs,
                total=total,
                batch_size=100,
                market=market,
                context=execution_context,
            )
            processed = execution_context.processed
            refreshed = execution_result.refreshed
            failed = execution_result.failed

            success_rate = refreshed / total if total > 0 else 0
            status = "completed" if success_rate >= 0.95 else "partial"
            market_success_rates = {}
            for refresh_market, market_total in symbol_market_totals.items():
                market_success_rate = (
                    execution_result.refreshed_by_market[refresh_market] / market_total
                    if market_total > 0
                    else 0
                )
                if market_success_rate >= 0.95:
                    market_success_rates[refresh_market] = (
                        self._deps.market_calendar_service_factory().last_completed_trading_day(
                            refresh_market
                        ),
                        market_success_rate,
                    )

            self._schedule_failed_retries(
                execution_result.failed_symbols,
                execution_context=execution_context,
                activity_lifecycle=activity_lifecycle,
            )

            logger.info("=" * 80)
            logger.info("Smart refresh completed (%s mode):", parsed_mode.value)
            logger.info("  Refreshed: %s", refreshed)
            logger.info("  Failed: %s", failed)
            logger.info("  Total: %s", total)
            if execution_result.failed_symbols:
                logger.info("  Failed symbols: %s...", execution_result.failed_symbols[:10])
            logger.info("=" * 80)

            finalization = PriceRefreshFinalization(
                metadata_status=status,
                metadata_refreshed=refreshed,
                metadata_total=total,
                activity_current=total,
                activity_total=total,
                message=f"Price refresh {status}",
                market_success_rates=market_success_rates,
            )
            self._finalize_success(
                db,
                price_cache,
                task,
                market=market,
                effective_market=effective_market,
                activity_lifecycle=activity_lifecycle,
                finalization=finalization,
            )

            outcome = PriceRefreshOutcome(
                status=status,
                source=(
                    PriceRefreshSource.GITHUB_AND_LIVE
                    if refresh_plan.used_github_seed
                    else PriceRefreshSource.LIVE
                ),
                mode=parsed_mode,
                refreshed=refreshed,
                failed=failed,
                total=total,
                failed_symbols=execution_result.failed_symbols,
                github_seed=github_seed,
            )
            return outcome.to_task_result()

        except SoftTimeLimitExceeded:
            logger.error("Soft time limit exceeded in smart_refresh_cache", exc_info=True)
            self._deps.safe_rollback(db)
            current_progress = getattr(execution_context, "processed", processed)
            self._record_failure(
                db,
                price_cache,
                task,
                market=market,
                effective_market=effective_market,
                activity_lifecycle=activity_lifecycle,
                refreshed=refreshed,
                total=locals().get("total", 0),
                current=current_progress,
                message="Soft time limit exceeded",
            )
            raise
        except Exception as exc:
            self._deps.raise_if_transient_database_error(exc)
            logger.error("Error in smart_refresh_cache task: %s", exc, exc_info=True)
            self._deps.safe_rollback(db)
            current_progress = getattr(execution_context, "processed", processed)
            self._record_failure(
                db,
                price_cache,
                task,
                market=market,
                effective_market=effective_market,
                activity_lifecycle=activity_lifecycle,
                refreshed=refreshed,
                total=locals().get("total", 0),
                current=current_progress,
                message=str(exc),
            )
            return {
                "status": "failed",
                "error": str(exc),
                "refreshed": refreshed,
                "failed": failed,
                "mode": parsed_mode.value,
                "timestamp": datetime.now().isoformat(),
            }
        finally:
            db.close()

    def _should_reject_full_refresh(
        self,
        mode: PriceRefreshMode,
        task: CeleryTaskLike,
        market: str | None,
    ) -> bool:
        if mode is not PriceRefreshMode.FULL or market is not None:
            return False
        is_manual = (
            self._deps.time_window_bypass_enabled()
            or (
                getattr(getattr(task, "request", None), "headers", None)
                and task.request.headers.get("origin") == "manual"
            )
        )
        if is_manual:
            return False
        now_et = self._deps.get_eastern_now()
        weekday = now_et.weekday()
        hour = now_et.hour
        in_weekday_window = weekday < 5 and 16 <= hour < 24
        in_sunday_window = weekday == 6 and 1 <= hour < 6
        if in_weekday_window or in_sunday_window:
            return False
        logger.warning(
            "Rejecting Beat-scheduled full refresh outside time window "
            "(weekday=%s, hour=%s). Likely a catchup storm.",
            weekday,
            hour,
        )
        return True

    def _load_active_symbol_universe(
        self,
        db,
        *,
        market: str | None,
        effective_market: str,
    ) -> tuple[list[str], dict[str, str]]:
        from ..models.stock_universe import StockUniverse

        query = db.query(StockUniverse.symbol, StockUniverse.market).filter(
            StockUniverse.is_active == True
        )
        if market is not None:
            query = query.filter(StockUniverse.market == self._deps.normalize_market(market))
        query = query.order_by(StockUniverse.market_cap.desc().nullslast())
        universe_rows = query.all()
        all_symbols = [row.symbol for row in universe_rows]
        symbol_markets = {
            str(row.symbol).upper(): self._deps.normalize_market(
                getattr(row, "market", None) or effective_market
            )
            for row in universe_rows
        }
        return all_symbols, symbol_markets

    def _publish_github_seed_log(
        self,
        *,
        github_seed: GitHubSeedOutcome | None,
        refresh_plan: PriceRefreshPlan,
        effective_market: str,
        all_symbols: Sequence[str],
        activity_lifecycle: str,
        db,
        task: CeleryTaskLike,
        log_extra: Mapping[str, Any],
    ) -> None:
        if github_seed and github_seed.stale_reason:
            logger.info(
                "GitHub daily price bundle for %s imported with stale manifest: %s",
                effective_market,
                github_seed.stale_reason,
                extra=log_extra,
            )
        if github_seed and not refresh_plan.used_github_seed:
            reason = github_seed.reason or github_seed.error
            logger.warning(
                "GitHub daily price bundle not used for %s (status=%s, reason=%s, stale_reason=%s); "
                "using live refresh policy",
                effective_market,
                github_seed.status_value,
                reason,
                github_seed.stale_reason,
                extra=log_extra,
            )
            self._deps.mark_market_activity_progress_safely(
                db,
                market=effective_market,
                stage_key="prices",
                lifecycle=activity_lifecycle,
                task_name=getattr(task, "name", "smart_refresh_cache"),
                task_id=getattr(getattr(task, "request", None), "id", None),
                current=0,
                total=len(all_symbols),
                percent=0,
                message=f"GitHub price bundle {github_seed.status_value}; using live price refresh",
            )

    def _log_live_symbol_plan(
        self,
        *,
        refresh_plan: PriceRefreshPlan,
        refresh_source: PriceRefreshSource,
        symbols: Sequence[str],
        mode: PriceRefreshMode,
        market: str | None,
        effective_market: str,
        log_extra: Mapping[str, Any],
    ) -> None:
        if not symbols:
            return
        if refresh_source is PriceRefreshSource.GITHUB_AND_LIVE:
            logger.info(
                "GitHub daily price bundle synced for %s; live refresh will top up %d symbols",
                effective_market,
                len(symbols),
                extra=log_extra,
            )
        elif mode is PriceRefreshMode.FULL:
            logger.info(
                "Full refresh: %d symbols (market cap order) %s",
                len(symbols),
                self._deps.market_tag(market),
                extra=log_extra,
            )
        elif mode in {PriceRefreshMode.BOOTSTRAP, PriceRefreshMode.DELTA}:
            logger.info(
                "Delta refresh: %d symbols %s",
                len(symbols),
                self._deps.market_tag(market),
                extra=log_extra,
            )

    def _completion_trading_day(
        self,
        github_seed: GitHubSeedOutcome | None,
        effective_market: str,
    ):
        if github_seed and github_seed.as_of_date is not None:
            return github_seed.as_of_date
        return self._deps.market_calendar_service_factory().last_completed_trading_day(
            effective_market
        )

    @staticmethod
    def _empty_refresh_message(
        refresh_plan: PriceRefreshPlan,
        mode: PriceRefreshMode,
    ) -> str:
        if refresh_plan.completion_message:
            return refresh_plan.completion_message
        if mode is PriceRefreshMode.AUTO:
            return "All symbols recently refreshed - nothing to do"
        if mode in {PriceRefreshMode.BOOTSTRAP, PriceRefreshMode.DELTA}:
            return "All symbols already fresh - no live fetch needed"
        return "No active symbols found in universe"

    @staticmethod
    def _github_seed_from_plan(refresh_plan: PriceRefreshPlan) -> GitHubSeedOutcome | None:
        github_seed = getattr(refresh_plan, "github_seed", None)
        if github_seed is not None:
            return github_seed
        return GitHubSeedOutcome.from_mapping(getattr(refresh_plan, "github_sync", None))

    @staticmethod
    def _source_from_plan(refresh_plan: PriceRefreshPlan) -> PriceRefreshSource:
        source = getattr(refresh_plan, "source", PriceRefreshSource.LIVE)
        if isinstance(source, PriceRefreshSource):
            return source
        return PriceRefreshSource(str(source))

    def _finalize_success(
        self,
        db,
        price_cache,
        task: CeleryTaskLike,
        *,
        market: str | None,
        effective_market: str,
        activity_lifecycle: str,
        finalization: PriceRefreshFinalization,
    ) -> None:
        price_cache.save_warmup_metadata(
            finalization.metadata_status,
            finalization.metadata_refreshed,
            finalization.metadata_total,
            market=market,
        )
        if finalization.heartbeat_status is not None:
            price_cache.complete_warmup_heartbeat(
                finalization.heartbeat_status,
                market=market,
            )
        self._deps.mark_market_activity_completed(
            db,
            market=effective_market,
            stage_key="prices",
            lifecycle=activity_lifecycle,
            task_name=getattr(task, "name", "smart_refresh_cache"),
            task_id=getattr(getattr(task, "request", None), "id", None),
            current=finalization.activity_current,
            total=finalization.activity_total,
            message=finalization.message,
        )
        for refresh_market, (trading_day, success_rate) in finalization.market_success_rates.items():
            self._deps.record_market_refresh_success(
                db,
                market=refresh_market,
                trading_day=trading_day,
                success_rate=success_rate,
            )

    def _record_failure(
        self,
        db,
        price_cache,
        task: CeleryTaskLike,
        *,
        market: str | None,
        effective_market: str,
        activity_lifecycle: str,
        refreshed: int,
        total: int,
        current: int,
        message: str,
    ) -> None:
        price_cache.save_warmup_metadata(
            "failed",
            refreshed,
            total,
            message,
            market=market,
        )
        price_cache.complete_warmup_heartbeat("failed", market=market)
        self._deps.mark_market_activity_failed_safely(
            db,
            market=effective_market,
            stage_key="prices",
            lifecycle=activity_lifecycle,
            task_name=getattr(task, "name", "smart_refresh_cache"),
            task_id=getattr(getattr(task, "request", None), "id", None),
            current=current,
            total=total,
            message=message,
        )

    def _schedule_failed_retries(
        self,
        failed_symbols: Sequence[str],
        *,
        execution_context: LivePriceRefreshExecutionContext,
        activity_lifecycle: str,
    ) -> None:
        if not failed_symbols:
            return
        failed_symbols_by_market: dict[str, list[str]] = {}
        for symbol in failed_symbols:
            failed_symbols_by_market.setdefault(
                execution_context.market_for_symbol(symbol),
                [],
            ).append(symbol)
        for retry_market, retry_symbols in failed_symbols_by_market.items():
            kwargs = {
                "symbols": retry_symbols,
                "market": retry_market,
                "attempt": 1,
            }
            if activity_lifecycle == "bootstrap":
                kwargs["countdown"] = 30
            self._deps.schedule_failed_symbol_retry(**kwargs)
