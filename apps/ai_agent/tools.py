"""Allowlisted CARVIX tool dispatch and execution audit boundary."""

import logging
import time
from collections.abc import Mapping

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from .booking_tool import TOOL_NAME, book_maintenance_appointment
from .models import AgentActionLog
from .sanitization import sanitize_payload


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


# The production allowlist is deliberately explicit and contains one tool.
TOOL_REGISTRY = {}
_register_tool(TOOL_REGISTRY, TOOL_NAME, book_maintenance_appointment)


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
    """Dispatch a registered handler and audit exactly one execution attempt."""
    allowed_tools = TOOL_REGISTRY if registry is None else registry
    if (
        not isinstance(name, str)
        or not isinstance(allowed_tools, Mapping)
        or name not in allowed_tools
    ):
        return dict(_SAFE_UNAVAILABLE)

    started_ns = time.monotonic_ns()
    handler = allowed_tools[name]
    if not callable(handler):
        result = dict(_SAFE_UNAVAILABLE)
    else:
        try:
            handler_result = handler(actor=actor, arguments=arguments)
        except Exception as error:
            # Exception details can contain user data, credentials, or database internals.
            logger.error("Registered AI tool handler failed (%s).", type(error).__name__)
            handler_result = dict(_SAFE_INTERNAL_ERROR)
        result = _valid_result(handler_result)
        if result is None:
            result = dict(_SAFE_INVALID_RESULT)

    try:
        _write_audit(
            actor=actor,
            name=name,
            arguments=arguments,
            result=result,
            started_ns=started_ns,
        )
    except Exception as error:
        # Never retry a possibly completed insert or expose the database failure.
        logger.error("Registered AI tool audit write failed (%s).", type(error).__name__)
        return dict(_SAFE_INTERNAL_ERROR)
    return result
