"""Allowlisted CARVIX tool dispatch and execution audit boundary."""

import logging
import time
from collections.abc import Mapping

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from .booking_tool import TOOL_NAME, book_maintenance_appointment
from .maintenance_tool import check_required_maintenance
from .models import AgentActionLog
from .sanitization import sanitize_payload
from .slot_tool import list_available_service_slots
from .tool_schemas import TOOL_SCHEMAS


logger = logging.getLogger(__name__)
_RESULT_FIELDS = {"success", "code", "message", "data", "errors"}
_SAFE_UNAVAILABLE = {
    "success": False,
    "code": "unsupported_tool",
    "message": "That action is not available.",
    "data": None,
    "errors": None,
}
_SAFE_INTERNAL_ERROR = {
    "success": False,
    "code": "internal_error",
    "message": "The requested action could not be completed. Please try again later.",
    "data": None,
    "errors": None,
}
_SAFE_INVALID_RESULT = {
    "success": False,
    "code": "invalid_tool_result",
    "message": "The requested action returned an invalid result.",
    "data": None,
    "errors": None,
}


def _register_tool(registry, name, handler):
    """Add one explicit callable without allowing silent replacement."""
    if not isinstance(name, str) or not name or not callable(handler):
        return False
    if name in registry:
        return False
    registry[name] = handler
    return True


# Keep the production allowlist explicit. A duplicate or invalid declaration
# is a startup error instead of silently replacing an approved handler.
TOOL_REGISTRY = {}
for _name, _handler in (
    ("check_required_maintenance", check_required_maintenance),
    ("list_available_service_slots", list_available_service_slots),
    (TOOL_NAME, book_maintenance_appointment),
):
    if not _register_tool(TOOL_REGISTRY, _name, _handler):
        raise RuntimeError("The AI Tool Registry contains an invalid or duplicate Tool.")
if set(TOOL_REGISTRY) != set(TOOL_SCHEMAS):
    raise RuntimeError("The AI Tool Registry and internal Tool schemas do not match.")


def _valid_result(result):
    try:
        if not isinstance(result, Mapping) or set(result) != _RESULT_FIELDS:
            return None
        safe_result = sanitize_payload(dict(result))
    except Exception:
        return None
    if (
        not isinstance(safe_result.get("success"), bool)
        or not isinstance(safe_result.get("code"), str)
        or not isinstance(safe_result.get("message"), str)
        or (safe_result.get("data") is not None and not isinstance(safe_result["data"], dict))
        or (safe_result.get("errors") is not None and not isinstance(safe_result["errors"], dict))
    ):
        return None
    return safe_result


def _safe_arguments(arguments):
    if not isinstance(arguments, dict):
        return {"invalid_arguments": True}
    try:
        sanitized = sanitize_payload(arguments)
    except (ValidationError, TypeError, ValueError, OverflowError):
        return {"invalid_arguments": True}
    if not sanitized:
        # JSONField(blank=False) rejects {} during AgentActionLog.full_clean().
        # Keep the supplied empty object explicit inside a non-empty JSON object.
        return {"_supplied_arguments": {}}
    return sanitized


def _is_auditable_actor(actor):
    user_model = get_user_model()
    return (
        isinstance(actor, user_model)
        and bool(getattr(actor, "is_authenticated", False))
        and actor.pk is not None
    )


def _write_audit(*, actor, name, arguments, result, started_ns):
    if not _is_auditable_actor(actor):
        return False
    duration_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
    duration_ms = min(duration_ms, 2_147_483_647)
    AgentActionLog.objects.create(
        user=actor,
        tool_name=name,
        arguments=_safe_arguments(arguments),
        result=result,
        status=(
            AgentActionLog.Status.SUCCESS
            if result["success"]
            else AgentActionLog.Status.FAILURE
        ),
        duration_ms=duration_ms,
    )
    return True


def execute_tool_request(name, arguments, *, actor, registry=None):
    """Run a registered handler and coordinate its effect with its audit row."""
    allowed_tools = TOOL_REGISTRY if registry is None else registry
    if (
        not isinstance(name, str)
        or not isinstance(allowed_tools, Mapping)
        or name not in allowed_tools
    ):
        return dict(_SAFE_UNAVAILABLE)

    started_ns = time.monotonic_ns()
    handler = allowed_tools[name]
    failure_result = None
    success_result = None
    success_audit_attempted = False

    try:
        # The booking service uses a nested atomic block. Its Appointment remains
        # provisional until this outer block commits together with the audit row.
        with transaction.atomic():
            if not callable(handler):
                failure_result = dict(_SAFE_UNAVAILABLE)
                transaction.set_rollback(True)
            else:
                handler_result = handler(actor=actor, arguments=arguments)
                result = _valid_result(handler_result)
                if result is None:
                    failure_result = dict(_SAFE_INVALID_RESULT)
                    transaction.set_rollback(True)
                elif not result["success"]:
                    failure_result = result
                    transaction.set_rollback(True)
                else:
                    success_audit_attempted = True
                    if not _write_audit(
                        actor=actor,
                        name=name,
                        arguments=arguments,
                        result=result,
                        started_ns=started_ns,
                    ):
                        raise RuntimeError("Audit write was not available.")
                    success_result = result
    except Exception as error:
        # The atomic block has exited before logging or attempting a failure audit.
        if success_audit_attempted:
            # Do not retry: the success audit may have reached the database even
            # if its error was raised while the transaction was committing.
            logger.error("Registered AI tool audit write failed (%s).", type(error).__name__)
            return dict(_SAFE_INTERNAL_ERROR)
        logger.error("Registered AI tool handler failed (%s).", type(error).__name__)
        failure_result = dict(_SAFE_INTERNAL_ERROR)

    if success_result is not None:
        # Reaching here means both the handler and success audit committed.
        return success_result

    # Structured failures and unexpected Handler errors have rolled back before
    # this fresh failure-audit transaction begins.
    try:
        with transaction.atomic():
            _write_audit(
                actor=actor,
                name=name,
                arguments=arguments,
                result=failure_result,
                started_ns=started_ns,
            )
    except Exception as error:
        # Never retry a possibly completed insert or expose database details.
        logger.error("Registered AI tool audit write failed (%s).", type(error).__name__)
        return dict(_SAFE_INTERNAL_ERROR)
    return failure_result
