"""AI adapter for confirmed Owner appointment booking."""

from apps.appointments.services import AppointmentBookingError, book_appointment
from apps.authentication.models import User


TOOL_NAME = "book_maintenance_appointment"
_ARGUMENT_FIELDS = {"vehicle_id", "service_type_id", "slot_id", "confirmation"}
_ID_FIELDS = ("vehicle_id", "service_type_id", "slot_id")
_ID_MAX = 9_223_372_036_854_775_807

_RESULT_MESSAGES = {
    "ok": "The appointment was booked successfully.",
    "confirmation_required": "Confirm this booking before I can create it.",
    "validation_error": "The booking details are invalid. Check the selected vehicle, service, and slot.",
    "permission_denied": "You cannot book an appointment for that vehicle.",
    "not_found": "The selected service is unavailable.",
    "slot_unavailable": "That time slot is unavailable. Choose another slot.",
    "duplicate_booking": "This vehicle already has an active appointment in that time slot.",
    "internal_error": "The appointment could not be booked. Please try again later.",
}


def _result(success, code, *, data=None, errors=None):
    return {
        "success": success,
        "code": code,
        "message": _RESULT_MESSAGES[code],
        "data": data,
        "errors": errors,
    }


def _positive_identifier(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        try:
            parsed = int(value)
        except (ValueError, OverflowError):
            return None
    else:
        return None
    return parsed if 0 < parsed <= _ID_MAX else None


def _validate_arguments(arguments):
    if not isinstance(arguments, dict):
        return None, _result(
            False,
            "validation_error",
            errors={"arguments": "A booking argument object is required."},
        )
    if any(not isinstance(key, str) for key in arguments):
        return None, _result(
            False,
            "validation_error",
            errors={"arguments": "Argument names must be text fields."},
        )

    unknown = set(arguments) - _ARGUMENT_FIELDS
    missing = _ARGUMENT_FIELDS - set(arguments)
    missing_ids = missing & set(_ID_FIELDS)
    if unknown or missing_ids:
        errors = {key: "This field is not accepted." for key in sorted(unknown)}
        errors.update({key: "This field is required." for key in sorted(missing_ids)})
        return None, _result(False, "validation_error", errors=errors)
    if "confirmation" in missing:
        return None, _result(
            False,
            "confirmation_required",
            errors={"confirmation": "Explicit confirmation is required."},
        )

    normalized = {}
    errors = {}
    for field in _ID_FIELDS:
        value = _positive_identifier(arguments[field])
        if value is None:
            errors[field] = "Enter a positive whole-number identifier."
        else:
            normalized[field] = value

    confirmation = arguments["confirmation"]
    if type(confirmation) is not bool:
        errors["confirmation"] = "Confirmation must be a boolean value."
    if errors:
        return None, _result(False, "validation_error", errors=errors)
    if confirmation is not True:
        return None, _result(
            False,
            "confirmation_required",
            errors={"confirmation": "Explicit confirmation is required."},
        )
    return normalized, None


def _domain_failure(error):
    code = {
        "invalid_selection": "validation_error",
        "permission_denied": "permission_denied",
        "invalid_service": "not_found",
        "slot_unavailable": "slot_unavailable",
        "slot_inactive": "slot_unavailable",
        "slot_expired": "slot_unavailable",
        "slot_full": "slot_unavailable",
        "booking_conflict": "slot_unavailable",
        "duplicate_booking": "duplicate_booking",
    }.get(error.code, "internal_error")
    if code == "internal_error":
        return _result(False, code)
    error_field = "booking" if code in {"slot_unavailable", "duplicate_booking"} else code
    return _result(False, code, errors={error_field: _RESULT_MESSAGES[code]})


def book_maintenance_appointment(*, actor, arguments):
    """Book through the manual domain service after strict AI validation."""
    normalized, failure = _validate_arguments(arguments)
    if failure is not None:
        return failure

    if (
        not isinstance(actor, User)
        or not getattr(actor, "is_authenticated", False)
        or actor.pk is None
        or getattr(actor, "role", None) != User.Role.OWNER
    ):
        return _result(
            False,
            "permission_denied",
            errors={"actor": _RESULT_MESSAGES["permission_denied"]},
        )

    try:
        appointment = book_appointment(
            actor=actor,
            **normalized,
            booked_by_agent=True,
        )
    except AppointmentBookingError as error:
        return _domain_failure(error)

    if appointment is None or appointment.pk is None:
        return _result(False, "internal_error")

    return _result(
        True,
        "ok",
        data={
            "appointment_id": appointment.pk,
            "vehicle_id": appointment.vehicle_id,
            "service_type_id": appointment.service_type_id,
            "slot_id": appointment.slot_id,
            "status": appointment.status,
        },
    )
