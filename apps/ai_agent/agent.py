"""Request-local orchestration for safe CARVIX chat responses."""

from dataclasses import dataclass

from .context import build_safe_context
from .prompts import CARVIX_SYSTEM_PROMPT
from .provider import ProviderReply, ProviderUnavailable, get_provider
from .tools import execute_tool_request


@dataclass(frozen=True)
class ChatResult:
    success: bool
    code: str
    message: str
    data: dict | None = None
    errors: dict | None = None


def respond_to_message(*, user, message):
    context = build_safe_context(user)
    try:
        provider_reply = get_provider().generate(
            message=message,
            system_prompt=CARVIX_SYSTEM_PROMPT,
            context=context,
        )
    except ProviderUnavailable:
        return ChatResult(
            False,
            "provider_unavailable",
            "The assistant is temporarily unavailable. Please try again later.",
        )
    except Exception:
        # Provider exception details may contain credentials or user content.
        return ChatResult(
            False,
            "provider_error",
            "The assistant could not process that message. Please try again.",
        )

    if not isinstance(provider_reply, ProviderReply):
        return ChatResult(
            False,
            "provider_error",
            "The assistant returned an invalid response. Please try again.",
        )
    if provider_reply.tool_call is not None:
        request = provider_reply.tool_call
        if not isinstance(request, dict) or set(request) != {"name", "arguments"}:
            return ChatResult(
                False,
                "unsupported_tool",
                "That action is not available.",
            )
        tool_result = execute_tool_request(
            request["name"], request["arguments"], actor=user
        )
        return ChatResult(
            success=tool_result["success"],
            code=tool_result["code"],
            message=tool_result["message"],
            data={"tool_result": tool_result} if tool_result["success"] else None,
        )
    if not isinstance(provider_reply.text, str) or not provider_reply.text.strip():
        return ChatResult(
            False,
            "provider_error",
            "The assistant returned an invalid response. Please try again.",
        )
    return ChatResult(
        True,
        "ok",
        "Message received.",
        data={"assistant_message": provider_reply.text.strip()},
    )
