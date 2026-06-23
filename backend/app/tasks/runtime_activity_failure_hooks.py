"""Celery request hooks for publishing runtime activity after worker loss."""

from __future__ import annotations

import logging
from typing import Any

from celery import Task
from celery.worker.request import Request

from ..database import SessionLocal
from ..services.market_activity_service import mark_market_activity_failed
from ..wiring.bootstrap import (
    get_data_fetch_lock,
    get_price_cache,
    get_workload_coordination,
)
from .market_queues import normalize_market

logger = logging.getLogger(__name__)

SMART_REFRESH_TASK_NAME = "app.tasks.cache_tasks.smart_refresh_cache"

_TRACKED_TASKS = {
    SMART_REFRESH_TASK_NAME: {
        "stage_key": "prices",
        "default_lifecycle": "daily_refresh",
    },
}


def _exception_detail(exception: BaseException | None) -> str:
    if exception is None:
        return "unknown failure"
    return str(exception) or exception.__class__.__name__


def _warn_cleanup_failure(
    action: str,
    *,
    task_name: str,
    task_id: str,
    market: str,
) -> None:
    logger.warning(
        "Failed to %s after runtime activity failure",
        action,
        extra={
            "task_name": task_name,
            "task_id": task_id,
            "market": market,
        },
        exc_info=True,
    )


def publish_runtime_activity_failure(
    task_name: str | None,
    task_id: str | None,
    kwargs: dict[str, Any] | None,
    exception: BaseException | None,
) -> None:
    tracked_task = _TRACKED_TASKS.get(task_name)
    if tracked_task is None or not task_id:
        return

    kwargs = kwargs or {}
    market = normalize_market(kwargs.get("market") or "US")
    lifecycle = kwargs.get("activity_lifecycle") or tracked_task["default_lifecycle"]
    stage_key = tracked_task["stage_key"]
    message = f"Task worker exited before cleanup: {_exception_detail(exception)}"

    db = None
    try:
        db = SessionLocal()
        mark_market_activity_failed(
            db,
            market=market,
            stage_key=stage_key,
            lifecycle=lifecycle,
            task_name=task_name,
            task_id=task_id,
            message=message,
        )
    except Exception:
        logger.warning(
            "Failed to publish runtime activity failure",
            extra={
                "task_name": task_name,
                "task_id": task_id,
                "market": market,
                "stage_key": stage_key,
            },
            exc_info=True,
        )
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                _warn_cleanup_failure(
                    "close runtime activity database session",
                    task_name=task_name,
                    task_id=task_id,
                    market=market,
                )

    try:
        get_price_cache().complete_warmup_heartbeat("failed", market=market)
    except Exception:
        _warn_cleanup_failure(
            "complete warmup heartbeat",
            task_name=task_name,
            task_id=task_id,
            market=market,
        )

    try:
        get_data_fetch_lock().release(task_id, market=market)
    except Exception:
        _warn_cleanup_failure(
            "release data fetch lock",
            task_name=task_name,
            task_id=task_id,
            market=market,
        )

    try:
        coordination = get_workload_coordination()
    except Exception:
        _warn_cleanup_failure(
            "load workload coordination",
            task_name=task_name,
            task_id=task_id,
            market=market,
        )
        return

    try:
        coordination.release_market_workload(task_id, market=market)
    except Exception:
        _warn_cleanup_failure(
            "release market workload",
            task_name=task_name,
            task_id=task_id,
            market=market,
        )

    try:
        coordination.release_external_fetch(task_id)
    except Exception:
        _warn_cleanup_failure(
            "release external fetch",
            task_name=task_name,
            task_id=task_id,
            market=market,
        )


class RuntimeActivityFailureRequest(Request):
    def on_failure(self, exc_info, send_failed_event=True, return_ok=False):
        result = super().on_failure(
            exc_info,
            send_failed_event=send_failed_event,
            return_ok=return_ok,
        )
        publish_runtime_activity_failure(
            getattr(getattr(self, "task", None), "name", None),
            getattr(self, "id", None),
            getattr(self, "kwargs", None),
            getattr(exc_info, "exception", None),
        )
        return result


class RuntimeActivityTrackedTask(Task):
    Request = RuntimeActivityFailureRequest
