"""Build small, role-scoped, JSON-native context for a single chat request."""

from django.db.models import Count
from django.utils import timezone

from apps.authentication.models import User
from apps.appointments.models import ACTIVE_APPOINTMENT_STATUSES, Appointment
from apps.maintenance.models import ServiceType, TechnicianProfile
from apps.vehicles.models import Vehicle


CONTEXT_RECORD_LIMIT = 20


def build_safe_context(user):
    """Return only the authenticated user's role and permitted summaries."""
    context = {"username": user.get_username(), "role": user.role}
    # Every valid domain role can use the slot Tool, and Owners can also book.
    # Give the Provider existing service names/IDs without price or description.
    if user.role in User.Role.values:
        context["service_types"] = list(
            ServiceType.objects.order_by("name", "pk").values("id", "name")
        )

    if user.role == User.Role.OWNER:
        now = timezone.now()
        context["vehicles"] = list(
            Vehicle.objects.filter(owner=user)
            .order_by("id")
            .values("id", "manufacturer", "model", "model_year", "license_plate")[
                :CONTEXT_RECORD_LIMIT
            ]
        )
        context["upcoming_appointments"] = _appointment_summaries(
            Appointment.objects.filter(
                vehicle__owner=user,
                slot__start_time__gte=now,
                status__in=(
                    "PENDING",
                    "CONFIRMED",
                    "IN_PROGRESS",
                ),
            )
            .order_by("slot__start_time", "id")
            .values(
                "id", "status", "vehicle__license_plate", "service_type__name",
                "slot__start_time", "slot__end_time",
            )[:CONTEXT_RECORD_LIMIT]
        )
    elif user.role == User.Role.TECHNICIAN:
        try:
            profile_id = user.technician_profile.pk
        except TechnicianProfile.DoesNotExist:
            context["assigned_appointments"] = []
        else:
            context["assigned_appointments"] = _appointment_summaries(
                Appointment.objects.filter(
                    technician_id=profile_id,
                    status__in=ACTIVE_APPOINTMENT_STATUSES,
                )
                .order_by("slot__start_time", "id")
                .values(
                    "id", "status", "vehicle__license_plate", "service_type__name",
                    "slot__start_time", "slot__end_time",
                )[:CONTEXT_RECORD_LIMIT]
            )
    elif user.role == User.Role.ADMINISTRATOR:
        context["appointment_counts_by_status"] = {
            row["status"]: row["count"]
            for row in Appointment.objects.values("status")
            .annotate(count=Count("pk"))
            .order_by("status")
        }

    return context


def _appointment_summaries(rows):
    summaries = []
    for row in rows:
        summary = dict(row)
        summary["slot__start_time"] = row["slot__start_time"].isoformat()
        summary["slot__end_time"] = row["slot__end_time"].isoformat()
        summaries.append(summary)
    return summaries
