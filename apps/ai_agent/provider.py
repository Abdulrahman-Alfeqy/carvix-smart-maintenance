"""Narrow provider boundary; this foundation intentionally has no SDK."""

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
    """Return the configured provider adapter (unavailable in this plan)."""
    return UnavailableProvider()
