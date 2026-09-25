from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models


class ServiceSlot(models.Model):
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    capacity = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_time", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F("start_time")),
                name="appointments_slot_end_gt_start",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name="appointments_slot_capacity_gt_0",
            ),
        ]
        indexes = [
            models.Index(fields=("start_time",), name="appointments_slot_start_idx"),
            models.Index(
                fields=("is_active", "start_time"),
                name="appointments_active_start_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if (
            isinstance(self.start_time, datetime)
            and isinstance(self.end_time, datetime)
            and self.end_time <= self.start_time
        ):
            errors["end_time"] = "End time must be later than start time."
        try:
            if self.capacity is not None and int(self.capacity) <= 0:
                errors["capacity"] = "Capacity must be greater than zero."
        except (TypeError, ValueError):
            # Field-level validation reports malformed values during full_clean().
            pass
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.start_time} – {self.end_time} (capacity {self.capacity})"


class AppointmentStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    CONFIRMED = "CONFIRMED", "Confirmed"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


ACTIVE_APPOINTMENT_STATUSES = (
    AppointmentStatus.PENDING,
    AppointmentStatus.CONFIRMED,
    AppointmentStatus.IN_PROGRESS,
)

TERMINAL_APPOINTMENT_STATUSES = (
    AppointmentStatus.COMPLETED,
    AppointmentStatus.CANCELLED,
)


class Appointment(models.Model):
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    service_type = models.ForeignKey(
        "maintenance.ServiceType",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    slot = models.ForeignKey(
        "appointments.ServiceSlot",
        on_delete=models.PROTECT,
        related_name="appointments",
    )
    technician = models.ForeignKey(
        "maintenance.TechnicianProfile",
        on_delete=models.PROTECT,
        related_name="appointments",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
    )
    notes = models.TextField(blank=True, default="")
    booked_by_agent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=AppointmentStatus.values),
                name="appointments_status_valid",
            ),
            models.UniqueConstraint(
                fields=("slot", "vehicle"),
                condition=models.Q(status__in=ACTIVE_APPOINTMENT_STATUSES),
                name="appointments_active_slot_vehicle_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("slot", "status"),
                name="appointments_slot_status_idx",
            ),
        ]

    def __str__(self):
        return f"Appointment {self.pk} — {self.vehicle.license_plate} — {self.slot.start_time}"
