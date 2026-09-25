from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from unittest import skipIf

from django.test import TestCase, TransactionTestCase

from .models import Vehicle


User = get_user_model()
is_postgres = connection.vendor == "postgresql"


class VehicleModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="vehicle-owner",
            email="vehicle-owner@example.com",
            password="test-password",
        )

    def make_vehicle(self, **overrides):
        values = {
            "owner": self.owner,
            "manufacturer": "Toyota",
            "model": "Corolla",
            "model_year": 2022,
            "license_plate": "ABC-123",
            "current_mileage": 1000,
        }
        values.update(overrides)
        return Vehicle.objects.create(**values)

    def test_normalizes_approved_text_fields_on_save(self):
        vehicle = self.make_vehicle(
            manufacturer=" Toyota ",
            model=" Corolla ",
            license_plate="  ab-١٢٣ ب  ",
        )
        self.assertEqual(vehicle.manufacturer, "Toyota")
        self.assertEqual(vehicle.model, "Corolla")
        self.assertEqual(vehicle.license_plate, "AB-١٢٣ ب")

    def test_full_clean_normalizes_plate_and_rejects_negative_mileage(self):
        vehicle = Vehicle(
            owner=None,
            manufacturer=" Toyota ",
            model=" Corolla ",
            model_year=2022,
            license_plate=" abc-123 ",
            current_mileage=-1,
        )
        with self.assertRaises(ValidationError):
            vehicle.full_clean()
        self.assertEqual(vehicle.license_plate, "ABC-123")

    def test_owner_reverse_relationship_and_safe_string(self):
        vehicle = self.make_vehicle()
        self.assertEqual(self.owner.vehicles.get(), vehicle)
        self.assertEqual(str(vehicle), "ABC-123 — Toyota Corolla")
        self.assertNotIn(self.owner.username, str(vehicle))

    def test_required_fields(self):
        vehicle = Vehicle(
            owner=self.owner,
            manufacturer="",
            model="",
            model_year=None,
            license_plate="",
            current_mileage=None,
        )
        with self.assertRaises(ValidationError) as raised:
            vehicle.full_clean()
        self.assertEqual(
            set(raised.exception.message_dict),
            {
                "manufacturer",
                "model",
                "model_year",
                "license_plate",
                "current_mileage",
            },
        )

    def test_owner_deletion_is_protected(self):
        self.make_vehicle()
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_default_ordering_is_newest_first(self):
        first = self.make_vehicle(license_plate="FIRST")
        second = self.make_vehicle(license_plate="SECOND")
        Vehicle.objects.filter(pk=first.pk).update(created_at=first.created_at)
        Vehicle.objects.filter(pk=second.pk).update(created_at=first.created_at)
        self.assertEqual(list(Vehicle.objects.values_list("pk", flat=True)), [second.pk, first.pk])


@skipIf(not is_postgres, "Database constraint tests require PostgreSQL")
class VehiclePostgreSQLConstraintTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="plate-owner",
            email="plate-owner@example.com",
            password="test-password",
        )

    def vehicle(self, **overrides):
        values = {
            "owner": self.owner,
            "manufacturer": "Toyota",
            "model": "Corolla",
            "model_year": 2022,
            "license_plate": "ABC-123",
            "current_mileage": 10,
        }
        values.update(overrides)
        return Vehicle.objects.create(**values)

    def test_case_insensitive_plate_values_cannot_coexist(self):
        self.vehicle(license_plate="ABC-123")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.vehicle(license_plate="abc-123")

    def test_database_rejects_negative_mileage(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.vehicle(license_plate="NEGATIVE", current_mileage=-1)
