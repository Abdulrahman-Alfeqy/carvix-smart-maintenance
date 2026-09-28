"""Read-only AI adapter for the existing available-slot selector."""

import re
from datetime import date
from collections.abc import Mapping

from apps.appointments.selectors import get_available_service_slots
from apps.authentication.models import User
from apps.maintenance.models import ServiceType


_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_MAX_PRIMARY_KEY = (2**63) - 1
_SLOT_READ_ROLES = {
    User.Role.OWNER,
    User.Role.TECHNICIAN,
    User.Role.ADMINISTRATOR,
}


def _result(*, success, code, message, data=None, errors=None):
    return {
        "success": success,
        "code": code,
        "message": message,
        "data": data,
        "errors": errors,
    }


def _positive_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 < value <= _MAX_PRIMARY_KEY else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return None
        return parsed if 0 < parsed <= _MAX_PRIMARY_KEY else None
    return None


def _validate_preferred_date(value):
    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def list_available_service_slots(*, actor, arguments):
    """Return global eligible slots after validating the requested service/date.

    The existing domain has no ServiceSlot-to-ServiceType relation. A valid
    preferred_date is syntax-checked only; matching it to timezone-aware slot
    times is intentionally deferred until an authoritative rule exists.
    """
    if (
        not getattr(actor, "is_authenticated", False)
        or getattr(actor, "role", None) not in _SLOT_READ_ROLES
    ):
        return _result(
            success=False,
            code="permission_denied",
            message="Sign in with an authorized CARVIX role to view available slots.",
        )

    if not isinstance(arguments, Mapping):
        return _result(
            success=False,
            code="invalid_arguments",
            message="Provide a service identifier and optional preferred date.",
            errors={"arguments": "A valid argument object is required."},
        )
    keys = set(arguments)
    if "service_type_id" not in keys or keys - {"service_type_id", "preferred_date"}:
        return _result(
            success=False,
            code="invalid_arguments",
            message="Provide a service identifier and optional preferred date.",
            errors={"arguments": "Only service_type_id and preferred_date are accepted."},
        )

    service_type_id = _positive_id(arguments["service_type_id"])
    if service_type_id is None:
        return _result(
            success=False,
            code="invalid_arguments",
            message="Provide a valid service identifier.",
            errors={"service_type_id": "Enter a positive whole-number service identifier."},
        )

    preferred_date = None
    if "preferred_date" in arguments:
        preferred_date = _validate_preferred_date(arguments["preferred_date"])
        if preferred_date is None:
            return _result(
                success=False,
                code="invalid_arguments",
                message="Enter a valid preferred date in YYYY-MM-DD format.",
                errors={"preferred_date": "Enter a valid calendar date as YYYY-MM-DD."},
            )

    try:
        service_type = ServiceType.objects.filter(pk=service_type_id).only("pk", "name").first()
    except Exception:
        return _result(
            success=False,
            code="slots_unavailable",
            message="Available slots could not be retrieved right now.",
        )
    if service_type is None:
        return _result(
            success=False,
            code="invalid_service",
            message="The selected service is unavailable.",
            errors={"service_type_id": "Choose an existing service type."},
        )

    try:
        slots = get_available_service_slots()
        slot_data = [
            {
                "id": slot.pk,
                "start_time": slot.start_time.isoformat(),
                "end_time": slot.end_time.isoformat(),
                "remaining_capacity": slot.capacity - slot.active_appointment_count,
            }
            for slot in slots
        ]
    except Exception:
        # Keep database and serialization details out of the tool result.
        return _result(
            success=False,
            code="slots_unavailable",
            message="Available slots could not be retrieved right now.",
        )

    message = "Eligible service slots retrieved."
    if preferred_date is not None:
        message += " Preferred-date filtering is not available."

    return _result(
        success=True,
        code="ok",
        message=message,
        data={
            "service_type": {"id": service_type.pk, "name": service_type.name},
            "slots": slot_data,
        },
    )
