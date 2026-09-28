"""Narrow provider boundary shared by fake and live Provider adapters."""

from django.conf import settings

from dataclasses import dataclass


class ProviderUnavailable(Exception):
    """Raised when no approved language-model provider is configured."""


@dataclass(frozen=True)
class ProviderReply:
    text: str = ""
    tool_call: dict | None = None


class UnavailableProvider:
    def generate(self, *, message, system_prompt, context):
        raise ProviderUnavailable


def get_provider():
    """Return Gemini when configured, otherwise preserve safe unavailability."""
    api_key = getattr(settings, "GEMINI_API_KEY", "")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ProviderUnavailable

    from .live_provider import GeminiProvider

    return GeminiProvider(
        api_key=api_key.strip(),
        model=getattr(settings, "GEMINI_MODEL", "gemini-flash-latest"),
        timeout_seconds=getattr(settings, "GEMINI_TIMEOUT_SECONDS", "20"),
    )
