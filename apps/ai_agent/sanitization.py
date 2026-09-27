import math
import re

from django.core.exceptions import ValidationError


REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "apikey",
    "token",
    "authorization",
    "cookie",
    "credential",
    "sessionid",
    "databaseurl",
    "connectionstring",
    "dsn",
)


def _is_sensitive_key(key):
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize_json(value):
    """Return a JSON-native copy with credential-bearing values redacted."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError("Payload must contain finite JSON numbers.")
        return value
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError("Payload object keys must be strings.")
            sanitized[key] = REDACTED if _is_sensitive_key(key) else sanitize_json(item)
        return sanitized
    raise ValidationError("Payload must contain only JSON-compatible values.")


def sanitize_payload(value):
    if not isinstance(value, dict):
        raise ValidationError("Payload must be a JSON object.")
    return sanitize_json(value)
