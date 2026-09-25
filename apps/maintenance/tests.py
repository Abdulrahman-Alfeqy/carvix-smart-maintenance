from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from unittest import skipIf

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.appointments.models import Appointment, ServiceSlot
from apps.inventory.models import SparePart
from apps.vehicles.models import Vehicle

from .models import MaintenancePart, MaintenanceRecord, ServiceType, TechnicianProfile


User = get_user_model()
is_postgres = connection.vendor == "postgresql"


class MaintenanceFixtures(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="maintenance-owner",
            email="maintenance-owner@example.com",
            password="test-password",
        )
        self.tech_user = User.objects.create_user(
            username="maintenance-tech",
            email="maintenance-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        self.technician = TechnicianProfile.objects.create(
            user=self.tech_user,
            specialization="General service",
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Toyota",
            model="Corolla",
            model_year=2022,
            license_plate="MAINT-1",
            current_mileage=1000,
        )
        self.service_type = ServiceType.objects.create(
            name="Oil service",
            description="Engine oil service",
            interval_km=5000,
            interval_months=6,
            duration_minutes=45,
            price=Decimal("25.00"),
        )
        self.slot = ServiceSlot.objects.create(
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=45),
            capacity=2,
        )
        self.appointment = Appointment.objects.create(
            vehicle=self.vehicle,
            service_type=self.service_type,
            slot=self.slot,
            technician=self.technician,
        )

    def make_record(self, **overrides):
        values = {
            "vehicle": self.vehicle,
            "service_type": self.service_type,
            "technician": self.technician,
            "appointment": self.appointment,
            "service_date": timezone.localdate(),
            "mileage_at_service": 1000,
        }
        values.update(overrides)
        return MaintenanceRecord.objects.create(**values)


class TechnicianProfileTests(TestCase):
    def test_valid_technician_profile_and_normalization(self):
        user = User.objects.create_user(
            username="tech-profile",
            email="tech-profile@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        profile = TechnicianProfile(user=user, specialization="  Engine repair  ")
        profile.full_clean()
        self.assertEqual(profile.specialization, "Engine repair")
        profile.save()
        self.assertTrue(profile.is_available)
        self.assertEqual(str(profile), "tech-profile — Engine repair")

    def test_non_technician_is_rejected_by_full_clean(self):
        user = User.objects.create_user(
            username="not-tech",
            email="not-tech@example.com",
            password="test-password",
        )
        profile = TechnicianProfile(user=user, specialization="General")
        with self.assertRaises(ValidationError) as raised:
            profile.full_clean()
        self.assertIn("user", raised.exception.message_dict)

    def test_one_profile_per_user(self):
        user = User.objects.create_user(
            username="single-profile",
            email="single-profile@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        TechnicianProfile.objects.create(user=user, specialization="General")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TechnicianProfile.objects.create(user=user, specialization="Electrical")

    def test_user_deletion_is_protected(self):
        user = User.objects.create_user(
            username="protected-tech",
            email="protected-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        TechnicianProfile.objects.create(user=user, specialization="General")
        with self.assertRaises(ProtectedError):
            user.delete()


class ServiceTypeTests(TestCase):
    def make_service(self, **overrides):
        values = {
            "name": "  General service  ",
            "description": "Scheduled maintenance",
            "interval_km": 5000,
            "interval_months": 6,
            "duration_minutes": 60,
            "price": Decimal("0.00"),
        }
        values.update(overrides)
        return ServiceType(**values)

    def test_valid_creation_normalizes_name_and_string(self):
        service = self.make_service()
        service.full_clean()
        service.save()
        self.assertEqual(service.name, "General service")
        self.assertEqual(str(service), "General service")

    def test_required_fields_and_positive_value_validation(self):
        service = self.make_service(interval_km=0, interval_months=0, duration_minutes=0)
        with self.assertRaises(ValidationError) as raised:
            service.full_clean()
        self.assertTrue({"interval_km", "interval_months", "duration_minutes"}.issubset(raised.exception.message_dict))

    def test_required_fields_are_enforced(self):
        service = ServiceType(
            name="",
            description="",
            interval_km=None,
            interval_months=None,
            duration_minutes=None,
            price=None,
        )
        with self.assertRaises(ValidationError):
            service.full_clean()

    def test_unique_name(self):
        self.make_service().save()
        duplicate = self.make_service(name="General service")
        with self.assertRaises(ValidationError):
            duplicate.full_clean()

    def test_negative_price_validation(self):
        service = self.make_service(price=Decimal("-0.01"))
        with self.assertRaises(ValidationError):
            service.full_clean()


class MaintenanceRecordTests(MaintenanceFixtures):
    def test_required_relationships(self):
        record = MaintenanceRecord(
            service_date=timezone.localdate(),
            mileage_at_service=0,
        )
        with self.assertRaises(ValidationError) as raised:
            record.full_clean()
        self.assertTrue({"vehicle", "service_type", "technician", "appointment"}.issubset(raised.exception.message_dict))

    def test_valid_record_and_required_relationships(self):
        record = self.make_record()
        self.assertEqual(record.vehicle.maintenance_records.get(), record)
        self.assertEqual(record.appointment.maintenance_records.get(), record)
        self.assertIn("MAINT-1", str(record))
        self.assertIn("Oil service", str(record))

    def test_future_date_and_mileage_validation(self):
        record = MaintenanceRecord(
            vehicle=self.vehicle,
            service_type=self.service_type,
            technician=self.technician,
            appointment=self.appointment,
            service_date=timezone.localdate() + timedelta(days=1),
            mileage_at_service=-1,
        )
        with self.assertRaises(ValidationError) as raised:
            record.full_clean()
        self.assertIn("service_date", raised.exception.message_dict)
        self.assertIn("mileage_at_service", raised.exception.message_dict)

    def test_relationship_mismatch_is_rejected(self):
        other_vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="MAINT-2",
            current_mileage=500,
        )
        record = MaintenanceRecord(
            vehicle=other_vehicle,
            service_type=self.service_type,
            technician=self.technician,
            appointment=self.appointment,
            service_date=timezone.localdate(),
            mileage_at_service=500,
        )
        with self.assertRaises(ValidationError) as raised:
            record.full_clean()
        self.assertIn("vehicle", raised.exception.message_dict)

    def test_service_and_technician_mismatches_are_rejected(self):
        other_service = ServiceType.objects.create(
            name="Other service",
            description="Test service",
            interval_km=1000,
            interval_months=3,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        other_tech_user = User.objects.create_user(
            username="other-maintenance-tech",
            email="other-maintenance-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        other_technician = TechnicianProfile.objects.create(
            user=other_tech_user,
            specialization="Other",
        )
        for field, value in (("service_type", other_service), ("technician", other_technician)):
            with self.subTest(field=field):
                record = MaintenanceRecord(
                    vehicle=self.vehicle,
                    service_type=value if field == "service_type" else self.service_type,
                    technician=value if field == "technician" else self.technician,
                    appointment=self.appointment,
                    service_date=timezone.localdate(),
                    mileage_at_service=500,
                )
                with self.assertRaises(ValidationError) as raised:
                    record.full_clean()
                self.assertIn(field, raised.exception.message_dict)

    def test_appointment_foreign_key_is_non_unique(self):
        first = self.make_record()
        second = self.make_record(mileage_at_service=1100)
        self.assertEqual(self.appointment.maintenance_records.count(), 2)
        self.assertNotEqual(first.pk, second.pk)

    def test_all_referenced_domain_deletions_are_protected(self):
        self.make_record()
        for related in (self.vehicle, self.service_type, self.technician, self.appointment):
            with self.subTest(related=related.__class__.__name__):
                with self.assertRaises(ProtectedError):
                    related.delete()


class MaintenancePartTests(MaintenanceFixtures):
    def setUp(self):
        super().setUp()
        self.record = self.make_record()
        self.part = SparePart.objects.create(
            name="Oil filter",
            part_number="OF-1",
            quantity=10,
            minimum_stock=2,
            unit_price=Decimal("5.00"),
        )

    def test_valid_creation_and_string(self):
        item = MaintenancePart.objects.create(
            maintenance_record=self.record,
            spare_part=self.part,
            quantity_used=1,
        )
        self.assertEqual(self.record.maintenance_parts.get(), item)
        self.assertIn("OF-1", str(item))
        self.assertIn("1", str(item))

    def test_quantity_must_be_positive(self):
        item = MaintenancePart(
            maintenance_record=self.record,
            spare_part=self.part,
            quantity_used=0,
        )
        with self.assertRaises(ValidationError):
            item.full_clean()

    def test_record_and_part_deletion_are_protected(self):
        MaintenancePart.objects.create(
            maintenance_record=self.record,
            spare_part=self.part,
            quantity_used=1,
        )
        with self.assertRaises(ProtectedError):
            self.record.delete()
        with self.assertRaises(ProtectedError):
            self.part.delete()

    def test_record_part_pair_is_unique(self):
        MaintenancePart.objects.create(
            maintenance_record=self.record,
            spare_part=self.part,
            quantity_used=1,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaintenancePart.objects.create(
                    maintenance_record=self.record,
                    spare_part=self.part,
                    quantity_used=2,
                )


@skipIf(not is_postgres, "Database constraint tests require PostgreSQL")
class MaintenancePostgreSQLConstraintTests(TransactionTestCase):
    def test_service_interval_constraint_rejects_zero(self):
        base_values = {
            "description": "test",
            "interval_km": 100,
            "interval_months": 1,
            "duration_minutes": 10,
            "price": Decimal("0.00"),
        }
        invalid_values = (
            {"interval_km": 0},
            {"interval_months": 0},
            {"duration_minutes": 0},
            {"price": Decimal("-0.01")},
        )
        for index, invalid in enumerate(invalid_values):
            with self.subTest(invalid=invalid):
                values = {**base_values, **invalid}
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        ServiceType.objects.create(name=f"Invalid service {index}", **values)

    def test_unique_service_name_is_enforced_by_database(self):
        service_values = {
            "description": "test",
            "interval_km": 100,
            "interval_months": 1,
            "duration_minutes": 10,
            "price": Decimal("0.00"),
        }
        ServiceType.objects.create(name="Unique service", **service_values)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServiceType.objects.create(name="Unique service", **service_values)

    def test_record_mileage_constraint_rejects_negative_value(self):
        # Related objects are built directly to keep this database-level assertion isolated.
        user = User.objects.create_user(
            username="constraint-owner",
            email="constraint-owner@example.com",
            password="test-password",
        )
        tech_user = User.objects.create_user(
            username="constraint-tech",
            email="constraint-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        technician = TechnicianProfile.objects.create(user=tech_user, specialization="General")
        vehicle = Vehicle.objects.create(
            owner=user,
            manufacturer="Toyota",
            model="Yaris",
            model_year=2021,
            license_plate="CONSTRAINT-1",
            current_mileage=0,
        )
        service = ServiceType.objects.create(
            name="Constraint service",
            description="test",
            interval_km=100,
            interval_months=1,
            duration_minutes=10,
            price=Decimal("1.00"),
        )
        now = timezone.now()
        slot = ServiceSlot.objects.create(start_time=now, end_time=now + timedelta(hours=1), capacity=1)
        appointment = Appointment.objects.create(
            vehicle=vehicle,
            service_type=service,
            slot=slot,
            technician=technician,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaintenanceRecord.objects.create(
                    vehicle=vehicle,
                    service_type=service,
                    technician=technician,
                    appointment=appointment,
                    service_date=timezone.localdate(),
                    mileage_at_service=-1,
                )

    def test_maintenance_part_quantity_constraint_rejects_zero(self):
        user = User.objects.create_user(
            username="part-constraint-owner",
            email="part-constraint-owner@example.com",
            password="test-password",
        )
        tech_user = User.objects.create_user(
            username="part-constraint-tech",
            email="part-constraint-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        technician = TechnicianProfile.objects.create(user=tech_user, specialization="General")
        vehicle = Vehicle.objects.create(
            owner=user,
            manufacturer="Toyota",
            model="Yaris",
            model_year=2021,
            license_plate="PART-CONSTRAINT-1",
            current_mileage=0,
        )
        service = ServiceType.objects.create(
            name="Part constraint service",
            description="test",
            interval_km=100,
            interval_months=1,
            duration_minutes=10,
            price=Decimal("1.00"),
        )
        now = timezone.now()
        slot = ServiceSlot.objects.create(start_time=now, end_time=now + timedelta(hours=1), capacity=1)
        appointment = Appointment.objects.create(
            vehicle=vehicle,
            service_type=service,
            slot=slot,
            technician=technician,
        )
        record = MaintenanceRecord.objects.create(
            vehicle=vehicle,
            service_type=service,
            technician=technician,
            appointment=appointment,
            service_date=timezone.localdate(),
            mileage_at_service=0,
        )
        part = SparePart.objects.create(
            name="Filter",
            part_number="PART-1",
            quantity=1,
            minimum_stock=0,
            unit_price=Decimal("1.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                MaintenancePart.objects.create(
                    maintenance_record=record,
                    spare_part=part,
                    quantity_used=0,
                )
