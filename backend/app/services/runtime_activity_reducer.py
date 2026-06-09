"""Pure transition rules for persisted runtime market activity."""

from __future__ import annotations

from collections.abc import Mapping, Set
from dataclasses import dataclass
from typing import Any

from .runtime_activity_contract import stage_index

_OPTIONAL_FAILURE_SCAN_SUPERSEDE_STAGES = frozenset({"groups"})


@dataclass(frozen=True)
class RuntimeActivityTransition:
    should_persist: bool
    payload: dict[str, Any]


def reduce_market_activity(
    existing_payload: Mapping[str, Any] | None,
    incoming_payload: Mapping[str, Any],
    *,
    preserve_existing_statuses: Set[str] | None = None,
) -> RuntimeActivityTransition:
    """Return the activity payload that should win this state transition."""
    payload = dict(incoming_payload)
    if not preserve_existing_statuses or not isinstance(existing_payload, Mapping):
        return RuntimeActivityTransition(should_persist=True, payload=payload)

    existing = dict(existing_payload)
    existing_status = existing.get("status")
    if existing_status not in preserve_existing_statuses:
        return RuntimeActivityTransition(should_persist=True, payload=payload)

    payload_status = payload.get("status")
    same_task = existing.get("task_id") == payload.get("task_id")
    same_stage = existing.get("stage_key") == payload.get("stage_key")
    same_owner = same_task and same_stage

    if existing_status == "running":
        if payload_status == "queued" or (
            payload_status != "failed" and not same_owner
        ):
            return RuntimeActivityTransition(should_persist=False, payload=existing)
        if payload_status == "failed" and not same_owner:
            return RuntimeActivityTransition(should_persist=False, payload=existing)
    elif existing_status == "completed":
        if payload_status != "failed":
            incoming_new_cycle = (
                payload_status in {"queued", "running"} and not same_owner
            )
            if not incoming_new_cycle:
                return RuntimeActivityTransition(should_persist=False, payload=existing)
    elif existing_status == "failed":
        supersedes_failed_activity = _should_supersede_failed_activity(existing, payload)
        incoming_new_cycle = payload_status in {"queued", "running"} and not same_owner
        if incoming_new_cycle:
            existing_stage_index = stage_index(existing.get("stage_key"))
            payload_stage_index = stage_index(payload.get("stage_key"))
            lifecycle_changed = existing.get("lifecycle") != payload.get("lifecycle")
            incoming_new_cycle = (
                lifecycle_changed or payload_stage_index <= existing_stage_index
            )
        if supersedes_failed_activity:
            pass
        elif payload_status == "failed" and same_owner:
            if _should_preserve_existing_failed_message(existing, payload):
                return RuntimeActivityTransition(should_persist=False, payload=existing)
        elif not incoming_new_cycle:
            return RuntimeActivityTransition(should_persist=False, payload=existing)

    return RuntimeActivityTransition(should_persist=True, payload=payload)


def _should_preserve_existing_failed_message(
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    existing_message = str(existing_payload.get("message") or "").strip()
    incoming_message = str(payload.get("message") or "").strip()
    return bool(
        existing_message
        and incoming_message
        and existing_message != incoming_message
        and len(existing_message) >= len(incoming_message)
    )


def _should_supersede_failed_activity(
    existing_payload: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    """Allow a real scan stage to replace stale optional-stage failures."""
    if existing_payload.get("stage_key") not in _OPTIONAL_FAILURE_SCAN_SUPERSEDE_STAGES:
        return False
    if payload.get("status") not in {"running", "completed"}:
        return False
    if payload.get("stage_key") != "scan":
        return False
    if existing_payload.get("lifecycle") != payload.get("lifecycle"):
        return False
    if payload.get("lifecycle") != "bootstrap":
        return False
    return stage_index(payload.get("stage_key")) > stage_index(
        existing_payload.get("stage_key")
    )
