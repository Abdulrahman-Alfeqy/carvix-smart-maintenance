import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower


def normalize_license_plate(value):
    """Trim a plate and uppercase Latin letters while preserving other scripts."""
    if not isinstance(value, str):
        return value
    normalized = []
    for character in value.strip():
        unicode_name = unicodedata.name(character, "")
        if character.isalpha() and "LATIN" in unicode_name:
            normalized.append(character.upper())
        else:
            normalized.append(character)
    return "".join(normalized)


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class Vehicle(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vehicles",
    )
    manufacturer = models.CharField(max_length=150)
    model = models.CharField(max_length=150)
    model_year = models.PositiveIntegerField()
    license_plate = models.CharField(max_length=32)
    current_mileage = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                Lower("license_plate"),
                name="vehicles_plate_ci_uniq",
            ),
            models.CheckConstraint(
                condition=models.Q(current_mileage__gte=0),
                name="vehicles_mileage_gte_0",
            ),
        ]

    def _normalize_fields(self):
        self.manufacturer = _strip(self.manufacturer)
        self.model = _strip(self.model)
        self.license_plate = normalize_license_plate(self.license_plate)

    def clean(self):
        super().clean()
        self._normalize_fields()
        errors = {}
        if isinstance(self.current_mileage, int) and self.current_mileage < 0:
            errors["current_mileage"] = "Mileage cannot be negative."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        # Normalize only approved text fields; save() deliberately does not call full_clean().
        self._normalize_fields()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.license_plate} — {self.manufacturer} {self.model}"
