from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from unittest import skipIf

from django.test import TestCase, TransactionTestCase

from .models import SparePart


is_postgres = connection.vendor == "postgresql"


class SparePartModelTests(TestCase):
    def make_part(self, **overrides):
        values = {
            "name": "  Oil filter  ",
            "part_number": "  OF-100  ",
            "quantity": 10,
            "minimum_stock": 2,
            "unit_price": Decimal("5.25"),
        }
        values.update(overrides)
        return SparePart(**values)

    def test_valid_creation_strips_text_and_string_representation(self):
        part = self.make_part()
        part.full_clean()
        part.save()
        self.assertEqual(part.name, "Oil filter")
        self.assertEqual(part.part_number, "OF-100")
        self.assertEqual(str(part), "OF-100 — Oil filter")

    def test_required_fields(self):
        part = SparePart(name="", part_number="", quantity=None, minimum_stock=None, unit_price=None)
        with self.assertRaises(ValidationError) as raised:
            part.full_clean()
        self.assertTrue({"name", "part_number", "quantity", "minimum_stock", "unit_price"}.issubset(raised.exception.message_dict))

    def test_non_negative_values_are_checked_by_model_validation(self):
        for field, value in (
            ("quantity", -1),
            ("minimum_stock", -1),
            ("unit_price", Decimal("-0.01")),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    self.make_part(**{field: value}).full_clean()

    def test_unique_part_number(self):
        self.make_part().save()
        duplicate = self.make_part(name="Replacement filter")
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_ordering(self):
        z_part = self.make_part(name="Z part", part_number="Z-1")
        a_part = self.make_part(name="A part", part_number="A-1")
        z_part.save()
        a_part.save()
        self.assertEqual(list(SparePart.objects.values_list("name", flat=True)), ["A part", "Z part"])


@skipIf(not is_postgres, "Database constraint tests require PostgreSQL")
class SparePartPostgreSQLConstraintTests(TransactionTestCase):
    def create_part(self, **overrides):
        values = {
            "name": "Oil filter",
            "part_number": "OF-200",
            "quantity": 10,
            "minimum_stock": 2,
            "unit_price": Decimal("5.25"),
        }
        values.update(overrides)
        return SparePart.objects.create(**values)

    def test_database_rejects_duplicate_part_number(self):
        self.create_part()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_part(name="Duplicate")

    def test_database_checks_reject_negative_quantities_and_price(self):
        for overrides in (
            {"part_number": "NEG-Q", "quantity": -1},
            {"part_number": "NEG-MIN", "minimum_stock": -1},
            {"part_number": "NEG-PRICE", "unit_price": Decimal("-0.01")},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        self.create_part(**overrides)
