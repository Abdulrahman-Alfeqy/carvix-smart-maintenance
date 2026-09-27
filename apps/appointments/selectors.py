from django.db.models import Count, F, Q
from django.utils import timezone

from .models import ACTIVE_APPOINTMENT_STATUSES, ServiceSlot


def get_available_service_slots():
    """Return active future service slots that still have capacity."""
    return (
        ServiceSlot.objects.filter(
            is_active=True,
            start_time__gt=timezone.now(),
        )
        .annotate(
            active_appointment_count=Count(
                "appointments",
                filter=Q(appointments__status__in=ACTIVE_APPOINTMENT_STATUSES),
            )
        )
        .filter(capacity__gt=F("active_appointment_count"))
    )
