"""Explicit allowlist boundary for future validated CARVIX tools."""

from collections.abc import Mapping


# Real maintenance, slot, and booking tools are intentionally deferred.
TOOL_REGISTRY = {}


def execute_tool_request(name, arguments, *, actor, registry=None):
    """Dispatch only a callable explicitly present in the supplied registry."""
    allowed_tools = TOOL_REGISTRY if registry is None else registry
    if not isinstance(name, str) or name not in allowed_tools:
        return {
            "success": False,
            "code": "unsupported_tool",
            "message": "That action is not available.",
            "data": None,
        }
    if not isinstance(arguments, dict):
        return {
            "success": False,
            "code": "invalid_tool_arguments",
            "message": "The requested action had invalid arguments.",
            "data": None,
        }
    handler = allowed_tools[name]
    if not callable(handler):
        return {
            "success": False,
            "code": "unsupported_tool",
            "message": "That action is not available.",
            "data": None,
        }
    result = handler(actor=actor, arguments=arguments)
    if (
        not isinstance(result, Mapping)
        or not isinstance(result.get("success"), bool)
        or not isinstance(result.get("code"), str)
        or not isinstance(result.get("message"), str)
        or (result.get("data") is not None and not isinstance(result.get("data"), dict))
    ):
        return {
            "success": False,
            "code": "invalid_tool_result",
            "message": "The requested action returned an invalid result.",
            "data": None,
        }
    return dict(result)
