"""Request-local, bounded orchestration for safe CARVIX chat responses."""

import json
import re
from copy import deepcopy
from dataclasses import dataclass

from .context import build_safe_context
from .prompts import CARVIX_SYSTEM_PROMPT
from .provider import ProviderReply, ProviderUnavailable, get_provider
from .sanitization import sanitize_payload
from .tool_schemas import TOOL_SCHEMAS
from .tools import TOOL_REGISTRY, execute_tool_request


MAX_TOOL_ROUNDS = 3
_RESULT_FIELDS = {"success", "code", "message", "data", "errors"}
_BOOKING_TOOL = "book_maintenance_appointment"
_MUTATION_INTENT_PATTERN = re.compile(
    r"\b(?:book|booking|schedule|reserve|confirm|cancel|delete|create|change|update)\b",
    re.IGNORECASE,
)
_GENERIC_COMPLETION_PATTERN = re.compile(
    r"\b(?:done|completed|all set|taken care of|finished|success(?:ful)?)\b",
    re.IGNORECASE,
)
_ACTION_SUCCESS_PATTERNS = (
    re.compile(
        r"\b(?:i|we)(?:\s+have|\s+just|['’]ve)?\s+(?:successfully\s+)?"
        r"(?:booked|reserved|scheduled|confirmed|created)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:your|the)\s+appointment\s+(?:is|was|has been)\s+"
        r"(?:now\s+)?(?:successfully\s+)?(?:booked|reserved|scheduled|confirmed|created)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:booking|appointment)\s+(?:was|is|has been)\s+(?:a\s+)?success(?:ful(?:ly)?)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:appointment|booking|reservation|slot)\b.{0,50}\b"
        r"(?:booked|reserved|scheduled|confirmed|created|successful|complete)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:booked|reserved|scheduled|confirmed|created)\b.{0,50}\b"
        r"(?:appointment|reservation|slot)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:successfully|success)\s+(?:booked|reserved|scheduled|confirmed|created)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class ChatResult:
    success: bool
    code: str
    message: str
    data: dict | None = None
    errors: dict | None = None


def _provider_context(application_context, observations, schema_names):
    """Return fresh JSON-native context including trusted schemas/observations."""
    context = deepcopy(application_context)
    context["tool_schemas"] = deepcopy(
        [TOOL_SCHEMAS[name] for name in schema_names if name in TOOL_SCHEMAS]
    )
    context["tool_observations"] = deepcopy(observations)
    return context


def _schemas_for_role(role):
    if role == "OWNER":
        return tuple(TOOL_SCHEMAS)
    if role in {"TECHNICIAN", "ADMINISTRATOR"}:
        return ("list_available_service_slots",)
    return ()


def _tool_observation(name, result):
    """Expose only the registered name and sanitized structured outcome."""
    if not isinstance(result, dict) or set(result) != _RESULT_FIELDS:
        result = {
            "success": False,
            "code": "internal_error",
            "message": "The requested action could not be completed. Please try again later.",
            "data": None,
            "errors": None,
        }
    observation = {
        "tool_name": name,
        "success": result["success"],
        "code": result["code"],
        "message": result["message"],
        "data": result["data"],
        "errors": result["errors"],
    }
    try:
        return sanitize_payload(observation)
    except Exception:
        return {
            "tool_name": name,
            "success": False,
            "code": "internal_error",
            "message": "The requested action could not be completed. Please try again later.",
            "data": None,
            "errors": None,
        }


def _request_fingerprint(name, arguments):
    """Canonicalize JSON requests so key order cannot bypass repeat checks."""
    if not isinstance(arguments, dict) or any(not isinstance(key, str) for key in arguments):
        return None
    try:
        return json.dumps(
            {"name": name, "arguments": arguments},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        return None


def _claims_action_success(text, user_message):
    if any(pattern.search(text) for pattern in _ACTION_SUCCESS_PATTERNS):
        return True
    return bool(
        _MUTATION_INTENT_PATTERN.search(user_message)
        and _GENERIC_COMPLETION_PATTERN.search(text)
    )


def _unverified_action_failure():
    message = "CARVIX cannot confirm that an appointment action succeeded without a successful backend Tool result."
    return ChatResult(
        False,
        "unverified_action_claim",
        message,
        data={"assistant_message": message},
    )


def _chat_data(*, assistant_message, observations, result=None):
    data = {"assistant_message": assistant_message}
    if result is not None:
        # Retain the original singular result key for current Chat consumers.
        data["tool_result"] = result
        data["tool_results"] = observations
    return data


def _from_tool_failure(result, observations):
    """Keep backend failure truth authoritative over any Provider prose."""
    return ChatResult(
        success=False,
        code=result["code"],
        message=result["message"],
        data=_chat_data(
            assistant_message=result["message"],
            observations=observations,
            result=result,
        ),
        errors=result["errors"],
    )


def _from_tool_success(result, observations, *, assistant_message=None):
    response_text = assistant_message or result["message"]
    return ChatResult(
        success=True,
        code=result["code"],
        message=result["message"],
        data=_chat_data(
            assistant_message=response_text,
            observations=observations,
            result=result,
        ),
    )


def _provider_failure(*, code, observations, failure_result, booking_result, last_result):
    if failure_result is not None:
        return _from_tool_failure(failure_result, observations)
    if booking_result is not None:
        # A Provider failure after commit must not imply that booking failed.
        message = booking_result["message"]
        return _from_tool_success(booking_result, observations, assistant_message=message)
    if last_result is not None:
        # The read completed, but no generated explanation was available.
        return _from_tool_success(last_result, observations, assistant_message=last_result["message"])
    if code == "provider_unavailable":
        return ChatResult(
            False,
            "provider_unavailable",
            "The assistant is temporarily unavailable. Please try again later.",
        )
    return ChatResult(
        False,
        "provider_error",
        "The assistant could not process that message. Please try again.",
    )


def _parse_reply(provider_reply):
    """Return (kind, value), rejecting mixed, malformed, or batched replies."""
    if not isinstance(provider_reply, ProviderReply):
        return "invalid", None
    if not isinstance(provider_reply.text, str):
        return "invalid", None
    if provider_reply.tool_call is None:
        if not provider_reply.text.strip():
            return "invalid", None
        return "text", provider_reply.text.strip()
    request = provider_reply.tool_call
    if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
        return "invalid", None
    if provider_reply.text.strip():
        # A single Provider turn cannot be both a user-facing completion and
        # an action request. Keep that ambiguous output away from dispatch.
        return "invalid", None
    if not isinstance(request["name"], str) or not request["name"]:
        return "invalid", None
    return "tool", request


def respond_to_message(*, user, message):
    """Run a bounded Provider/Tool observation loop for one authenticated turn."""
    application_context = build_safe_context(user)
    schema_names = _schemas_for_role(application_context.get("role"))
    try:
        provider = get_provider()
    except ProviderUnavailable:
        return _provider_failure(
            code="provider_unavailable",
            observations=[],
            failure_result=None,
            booking_result=None,
            last_result=None,
        )
    except Exception:
        return _provider_failure(
            code="provider_error",
            observations=[],
            failure_result=None,
            booking_result=None,
            last_result=None,
        )
    observations = []
    seen_requests = set()
    tool_rounds = 0
    last_result = None
    failure_result = None
    booking_result = None

    while True:
        try:
            # execute_tool_request owns and exits its transaction before the
            # loop calls the Provider again.
            provider_reply = provider.generate(
                message=message,
                system_prompt=CARVIX_SYSTEM_PROMPT,
                context=_provider_context(application_context, observations, schema_names),
            )
        except ProviderUnavailable:
            return _provider_failure(
                code="provider_unavailable",
                observations=observations,
                failure_result=failure_result,
                booking_result=booking_result,
                last_result=last_result,
            )
        except Exception:
            # Provider exception details may contain credentials or user content.
            return _provider_failure(
                code="provider_error",
                observations=observations,
                failure_result=failure_result,
                booking_result=booking_result,
                last_result=last_result,
            )

        kind, value = _parse_reply(provider_reply)
        if kind == "invalid":
            return _provider_failure(
                code="provider_error",
                observations=observations,
                failure_result=failure_result,
                booking_result=booking_result,
                last_result=last_result,
            )
        if kind == "text":
            if failure_result is not None:
                # Do not expose Provider text that could contradict a failed Tool.
                return _from_tool_failure(failure_result, observations)
            if last_result is None:
                if _claims_action_success(value, message):
                    return _unverified_action_failure()
                return ChatResult(
                    True,
                    "ok",
                    "Message received.",
                    data={"assistant_message": value},
                )
            if booking_result is None and _claims_action_success(value, message):
                return _unverified_action_failure()
            return _from_tool_success(last_result, observations, assistant_message=value)

        name = value["name"]
        arguments = value["arguments"]

        # A request for an unregistered name never reaches the dispatcher or audit.
        if name not in TOOL_REGISTRY:
            if failure_result is not None:
                return _from_tool_failure(failure_result, observations)
            if booking_result is not None:
                return _from_tool_success(
                    booking_result,
                    observations,
                    assistant_message="The appointment was booked successfully. No additional action was run.",
                )
            return ChatResult(False, "unsupported_tool", "That action is not available.")

        fingerprint = _request_fingerprint(name, arguments)
        if fingerprint is not None and fingerprint in seen_requests:
            if failure_result is not None:
                return _from_tool_failure(failure_result, observations)
            if booking_result is not None:
                return _from_tool_success(
                    booking_result,
                    observations,
                    assistant_message="The appointment was booked successfully. No additional booking was created.",
                )
            if last_result is not None:
                return _from_tool_success(last_result, observations)
            return ChatResult(False, "repeated_tool_call", "That request could not be repeated.")

        if failure_result is not None:
            # A Tool failure requires user clarification; do not launch another
            # execution automatically in the same turn.
            return _from_tool_failure(failure_result, observations)

        if name == _BOOKING_TOOL and booking_result is not None:
            # Never execute a second booking in the same Chat turn, even if the
            # Provider changes the vehicle, service, or slot arguments.
            return _from_tool_success(
                booking_result,
                observations,
                assistant_message="The appointment was booked successfully. No additional booking was created.",
            )

        if tool_rounds >= MAX_TOOL_ROUNDS:
            if booking_result is not None:
                return _from_tool_success(
                    booking_result,
                    observations,
                    assistant_message="The appointment was booked successfully. I stopped further Tool requests at the interaction limit.",
                )
            return ChatResult(
                False,
                "tool_round_limit",
                "I stopped further Tool requests at the interaction limit. Please continue with a new message.",
                data={"tool_results": observations} if observations else None,
            )

        if fingerprint is not None:
            seen_requests.add(fingerprint)
        tool_rounds += 1
        result = execute_tool_request(name, arguments, actor=user)
        if not isinstance(result, dict) or set(result) != _RESULT_FIELDS:
            # The production dispatcher already validates results. Keep a safe
            # fallback in case that boundary itself is replaced incorrectly.
            result = {
                "success": False,
                "code": "internal_error",
                "message": "The requested action could not be completed. Please try again later.",
                "data": None,
                "errors": None,
            }
        observation = _tool_observation(name, result)
        observations.append(observation)
        last_result = result
        if not result["success"]:
            failure_result = result
        elif name == _BOOKING_TOOL:
            booking_result = result
