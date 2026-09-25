from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils import timezone


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class TechnicianProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="technician_profile",
    )
    specialization = models.CharField(max_length=150)
    is_available = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]

    def clean(self):
        super().clean()
        self.specialization = _strip(self.specialization)
        if self.user_id:
            try:
                user = self.user
            except ObjectDoesNotExist:
                return
            if user.role != "TECHNICIAN":
                raise ValidationError({"user": "The related user must have the TECHNICIAN role."})

    def save(self, *args, **kwargs):
        self.specialization = _strip(self.specialization)
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} — {self.specialization}"


class ServiceType(models.Model):
    name = models.CharField(max_length=150)
    description = models.TextField()
    interval_km = models.PositiveIntegerField()
    interval_months = models.PositiveIntegerField()
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=("name",), name="maintenance_service_name_uniq"),
            models.CheckConstraint(
                condition=models.Q(interval_km__gt=0),
                name="maintenance_interval_km_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(interval_months__gt=0),
                name="maintenance_interval_months_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_minutes__gt=0),
                name="maintenance_duration_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="maintenance_price_gte_0",
            ),
        ]

    def _normalize_fields(self):
        self.name = _strip(self.name)

    def clean(self):
        super().clean()
        self._normalize_fields()
        errors = {}
        for field in ("interval_km", "interval_months", "duration_minutes"):
            value = getattr(self, field)
            try:
                if value is not None and int(value) <= 0:
                    errors[field] = "Value must be greater than zero."
            except (TypeError, ValueError):
                # Field-level validation reports malformed values during full_clean().
                pass
        try:
            if self.price is not None and Decimal(str(self.price)) < 0:
                errors["price"] = "Price cannot be negative."
        except (InvalidOperation, TypeError, ValueError):
            # Field-level validation reports malformed values during full_clean().
            pass
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self._normalize_fields()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class MaintenanceRecord(models.Model):
    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    service_type = models.ForeignKey(
        "maintenance.ServiceType",
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    technician = models.ForeignKey(
        "maintenance.TechnicianProfile",
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.PROTECT,
        related_name="maintenance_records",
    )
    service_date = models.DateField()
    mileage_at_service = models.PositiveIntegerField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-service_date", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mileage_at_service__gte=0),
                name="maintenance_record_mileage_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=("vehicle", "service_date"),
                name="maintenance_vehicle_date_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        service_date = (
            self.service_date.date()
            if isinstance(self.service_date, datetime)
            else self.service_date
        )
        if isinstance(service_date, date) and service_date > timezone.localdate():
            errors["service_date"] = "Service date cannot be in the future."
        if isinstance(self.mileage_at_service, int) and self.mileage_at_service < 0:
            errors["mileage_at_service"] = "Mileage cannot be negative."

        if self.appointment_id:
            try:
                appointment = self.appointment
            except (ObjectDoesNotExist, ValueError):
                appointment = None
            if appointment is not None:
                for record_field, appointment_field in (
                    ("vehicle", "vehicle"),
                    ("service_type", "service_type"),
                    ("technician", "technician"),
                ):
                    record_id = getattr(self, f"{record_field}_id")
                    appointment_id = getattr(appointment, f"{appointment_field}_id")
                    if record_id is not None and record_id != appointment_id:
                        errors[record_field] = (
                            f"The {record_field.replace('_', ' ')} must match the appointment."
                        )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.vehicle.license_plate} — {self.service_type} — {self.service_date}"


class MaintenancePart(models.Model):
    maintenance_record = models.ForeignKey(
        "maintenance.MaintenanceRecord",
        on_delete=models.PROTECT,
        related_name="maintenance_parts",
    )
    spare_part = models.ForeignKey(
        "inventory.SparePart",
        on_delete=models.PROTECT,
        related_name="maintenance_parts",
    )
    quantity_used = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=("maintenance_record", "spare_part"),
                name="maintenance_record_part_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity_used__gt=0),
                name="maintenance_part_quantity_gt_0",
            ),
        ]

    def clean(self):
        super().clean()
        if isinstance(self.quantity_used, int) and self.quantity_used <= 0:
            raise ValidationError({"quantity_used": "Quantity used must be greater than zero."})

    def __str__(self):
        return (
            f"Maintenance record {self.maintenance_record_id} — "
            f"{self.spare_part.part_number} × {self.quantity_used}"
        )
