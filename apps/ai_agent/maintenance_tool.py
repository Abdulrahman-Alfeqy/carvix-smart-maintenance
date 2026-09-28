"""Read-only AI adapter for the existing Owner due-service overview."""

from collections.abc import Mapping

from apps.authentication.models import User
from apps.maintenance.services import get_vehicle_maintenance_overview
from apps.vehicles.models import Vehicle


_MAX_PRIMARY_KEY = (2**63) - 1


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


def _json_due_service(result):
    record = result.last_service
    return {
        "service_type": {
            "id": result.service_type.pk,
            "name": result.service_type.name,
        },
        "status": result.status,
        "last_service": None if record is None else {
            "service_date": record.service_date.isoformat(),
            "mileage_at_service": record.mileage_at_service,
        },
        "next_due_mileage": result.next_due_mileage,
        "next_due_date": (
            result.next_due_date.isoformat()
            if result.next_due_date is not None
            else None
        ),
        "reason": result.reason,
    }


def check_required_maintenance(*, actor, arguments):
    """Return the due-service overview for an Owner's own Vehicle only."""
    if (
        not getattr(actor, "is_authenticated", False)
        or getattr(actor, "role", None) != User.Role.OWNER
    ):
        return _result(
            success=False,
            code="permission_denied",
            message="Only an authenticated Owner can check a vehicle's maintenance.",
        )

    if not isinstance(arguments, Mapping) or set(arguments) != {"vehicle_id"}:
        return _result(
            success=False,
            code="invalid_arguments",
            message="Provide only a valid vehicle identifier.",
            errors={"vehicle_id": "A valid vehicle identifier is required."},
        )
    vehicle_id = _positive_id(arguments["vehicle_id"])
    if vehicle_id is None:
        return _result(
            success=False,
            code="invalid_arguments",
            message="Provide only a valid vehicle identifier.",
            errors={"vehicle_id": "Enter a positive whole-number vehicle identifier."},
        )

    try:
        vehicle = Vehicle.objects.filter(owner=actor, pk=vehicle_id).first()
    except Exception:
        return _result(
            success=False,
            code="maintenance_unavailable",
            message="The maintenance overview is temporarily unavailable.",
        )
    if vehicle is None:
        return _result(
            success=False,
            code="vehicle_unavailable",
            message="This vehicle is unavailable for maintenance review.",
        )

    try:
        overview = get_vehicle_maintenance_overview(vehicle)
        services = [_json_due_service(item) for item in overview["due_services"]]
    except Exception:
        # Keep ORM or serializer details out of the tool result.
        return _result(
            success=False,
            code="maintenance_unavailable",
            message="The maintenance overview is temporarily unavailable.",
        )

    return _result(
        success=True,
        code="ok",
        message="Maintenance overview retrieved.",
        data={"vehicle_id": vehicle.pk, "services": services},
    )
