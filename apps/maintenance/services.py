"""Read-only maintenance history loading and due-service evaluation."""

from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from django.utils import timezone

from .models import MaintenanceRecord, ServiceType


@dataclass(frozen=True)
class DueServiceResult:
    service_type: ServiceType
    status: str
    last_service: MaintenanceRecord | None
    next_due_mileage: int | None
    next_due_date: date | None
    reason: str


_STATUS_RANK = {"NOT_DUE": 0, "DUE": 1, "OVERDUE": 2}


def add_calendar_months(value: date, months: int) -> date:
    """Add calendar months, clamping to the target month's final day."""
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def evaluate_due_services(
    current_mileage: int,
    service_types: list[ServiceType],
    records: list[MaintenanceRecord],
    as_of: date,
) -> list[DueServiceResult]:
    """Purely evaluate prepared, Vehicle-scoped records against service intervals."""
    latest_by_service: dict[int, MaintenanceRecord] = {}
    for record in records:
        latest_by_service.setdefault(record.service_type_id, record)

    results = []
    for service_type in service_types:
        latest = latest_by_service.get(service_type.pk)
        if latest is None:
            results.append(
                DueServiceResult(
                    service_type=service_type,
                    status="NO_HISTORY",
                    last_service=None,
                    next_due_mileage=None,
                    next_due_date=None,
                    reason="No recorded maintenance history is available for this service.",
                )
            )
            continue

        next_due_mileage = latest.mileage_at_service + service_type.interval_km
        next_due_date = add_calendar_months(latest.service_date, service_type.interval_months)
        dimensions: list[str] = []
        if current_mileage < latest.mileage_at_service:
            dimensions.append(
                "Mileage: unavailable "
                f"(current {current_mileage} is below latest service {latest.mileage_at_service})."
            )
            mileage_status = None
        else:
            mileage_status = (
                "NOT_DUE" if current_mileage < next_due_mileage
                else "DUE" if current_mileage == next_due_mileage
                else "OVERDUE"
            )
            dimensions.append(
                f"Mileage: {mileage_status} (current {current_mileage}, "
                f"next due {next_due_mileage})."
            )

        date_status = (
            "NOT_DUE" if as_of < next_due_date
            else "DUE" if as_of == next_due_date
            else "OVERDUE"
        )
        dimensions.append(
            f"Date: {date_status} (as of {as_of.isoformat()}, "
            f"next due {next_due_date.isoformat()})."
        )

        available_statuses = [status for status in (mileage_status, date_status) if status]
        status = max(available_statuses, key=_STATUS_RANK.__getitem__)
        results.append(
            DueServiceResult(
                service_type=service_type,
                status=status,
                last_service=latest,
                next_due_mileage=next_due_mileage,
                next_due_date=next_due_date,
                reason=" ".join(dimensions),
            )
        )
    return results


def get_vehicle_maintenance_overview(vehicle, as_of: date | None = None) -> dict:
    """Load one Vehicle's history and evaluate every configured ServiceType."""
    service_types = list(ServiceType.objects.order_by("name", "pk"))
    history = list(
        MaintenanceRecord.objects.filter(vehicle=vehicle)
        .select_related("service_type", "technician__user")
        .order_by("-service_date", "-pk")
    )
    due_services = evaluate_due_services(
        current_mileage=vehicle.current_mileage,
        service_types=service_types,
        records=history,
        as_of=as_of if as_of is not None else timezone.localdate(),
    )
    return {"history": history, "due_services": due_services}
