from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import models


def _strip(value):
    return value.strip() if isinstance(value, str) else value


class SparePart(models.Model):
    name = models.CharField(max_length=150)
    part_number = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    minimum_stock = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(fields=("part_number",), name="inventory_part_number_uniq"),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=0),
                name="inventory_part_quantity_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(minimum_stock__gte=0),
                name="inventory_min_stock_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="inventory_unit_price_gte_0",
            ),
        ]

    def _normalize_fields(self):
        self.name = _strip(self.name)
        self.part_number = _strip(self.part_number)

    def clean(self):
        super().clean()
        self._normalize_fields()
        errors = {}
        for field in ("quantity", "minimum_stock"):
            value = getattr(self, field)
            if isinstance(value, int) and value < 0:
                errors[field] = "Value cannot be negative."
        if errors:
            raise ValidationError(errors)
        try:
            if self.unit_price is not None and Decimal(str(self.unit_price)) < 0:
                raise ValidationError({"unit_price": "Unit price cannot be negative."})
        except (InvalidOperation, TypeError, ValueError):
            # Field-level validation reports malformed values during full_clean().
            pass

    def save(self, *args, **kwargs):
        self._normalize_fields()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.part_number} — {self.name}"
