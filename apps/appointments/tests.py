from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from unittest import skipIf

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.maintenance.models import ServiceType, TechnicianProfile
from apps.vehicles.models import Vehicle

from .models import (
    ACTIVE_APPOINTMENT_STATUSES,
    TERMINAL_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    ServiceSlot,
)


User = get_user_model()
is_postgres = connection.vendor == "postgresql"


class AppointmentFixtures(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="appointment-owner",
            email="appointment-owner@example.com",
            password="test-password",
        )
        self.tech_user = User.objects.create_user(
            username="appointment-tech",
            email="appointment-tech@example.com",
            password="test-password",
            role="TECHNICIAN",
        )
        self.technician = TechnicianProfile.objects.create(
            user=self.tech_user,
            specialization="General",
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Toyota",
            model="Yaris",
            model_year=2021,
            license_plate="APPT-1",
            current_mileage=500,
        )
        self.service_type = ServiceType.objects.create(
            name="Appointment service",
            description="Test service",
            interval_km=1000,
            interval_months=3,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        self.slot = self.make_slot()

    def make_slot(self, **overrides):
        start = timezone.now() + timedelta(days=1)
        values = {
            "start_time": start,
            "end_time": start + timedelta(minutes=30),
            "capacity": 2,
        }
        values.update(overrides)
        return ServiceSlot.objects.create(**values)

    def make_appointment(self, **overrides):
        values = {
            "vehicle": self.vehicle,
            "service_type": self.service_type,
            "slot": self.slot,
            "technician": self.technician,
        }
        values.update(overrides)
        return Appointment.objects.create(**values)


class ServiceSlotTests(AppointmentFixtures):
    def test_defaults_ordering_and_safe_string(self):
        slot = self.slot
        self.assertTrue(slot.is_active)
        self.assertEqual(list(ServiceSlot.objects.all()), [slot])
        self.assertIn(str(slot.start_time), str(slot))
        self.assertIn("capacity 2", str(slot))

    def test_timezone_aware_times(self):
        self.assertIsNotNone(self.slot.start_time.tzinfo)
        self.assertIsNotNone(self.slot.end_time.tzinfo)

    def test_end_time_and_capacity_validation(self):
        start = timezone.now()
        slot = ServiceSlot(start_time=start, end_time=start, capacity=0)
        with self.assertRaises(ValidationError) as raised:
            slot.full_clean()
        self.assertIn("end_time", raised.exception.message_dict)
        self.assertIn("capacity", raised.exception.message_dict)

    def test_indexes_are_declared(self):
        index_fields = {tuple(index.fields) for index in ServiceSlot._meta.indexes}
        self.assertIn(("start_time",), index_fields)
        self.assertIn(("is_active", "start_time"), index_fields)


class AppointmentModelTests(AppointmentFixtures):
    def test_required_relations(self):
        appointment = Appointment()
        with self.assertRaises(ValidationError) as raised:
            appointment.full_clean()
        self.assertTrue({"vehicle", "service_type", "slot"}.issubset(raised.exception.message_dict))

    def test_defaults_status_choices_and_nullable_technician(self):
        appointment = self.make_appointment(technician=None)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertFalse(appointment.booked_by_agent)
        self.assertIsNone(appointment.technician)
        self.assertEqual(
            set(AppointmentStatus.values),
            {"PENDING", "CONFIRMED", "IN_PROGRESS", "COMPLETED", "CANCELLED"},
        )
        self.assertEqual(
            set(ACTIVE_APPOINTMENT_STATUSES),
            {AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED, AppointmentStatus.IN_PROGRESS},
        )
        self.assertEqual(
            set(TERMINAL_APPOINTMENT_STATUSES),
            {AppointmentStatus.COMPLETED, AppointmentStatus.CANCELLED},
        )

    def test_required_relationships_and_reverse_relations(self):
        appointment = self.make_appointment()
        self.assertEqual(self.vehicle.appointments.get(), appointment)
        self.assertEqual(self.service_type.appointments.get(), appointment)
        self.assertEqual(self.slot.appointments.get(), appointment)
        self.assertEqual(self.technician.appointments.get(), appointment)
        self.assertIn("APPT-1", str(appointment))
        self.assertIn(str(self.slot.start_time), str(appointment))
        self.assertNotIn(self.owner.username, str(appointment))

    def test_invalid_status_is_rejected_by_full_clean(self):
        appointment = Appointment(
            vehicle=self.vehicle,
            service_type=self.service_type,
            slot=self.slot,
            status="UNKNOWN",
        )
        with self.assertRaises(ValidationError) as raised:
            appointment.full_clean()
        self.assertIn("status", raised.exception.message_dict)

    def test_ordering_is_newest_created_then_newest_id(self):
        first = self.make_appointment()
        second = self.make_appointment(status=AppointmentStatus.COMPLETED)
        Appointment.objects.filter(pk=first.pk).update(created_at=first.created_at)
        Appointment.objects.filter(pk=second.pk).update(created_at=first.created_at)
        self.assertEqual(list(Appointment.objects.values_list("pk", flat=True)), [second.pk, first.pk])

    def test_protected_relations_and_only_approved_composite_index(self):
        self.make_appointment()
        for related in (self.vehicle, self.service_type, self.slot, self.technician):
            with self.subTest(related=related.__class__.__name__):
                with self.assertRaises(ProtectedError):
                    related.delete()
        self.assertEqual([tuple(index.fields) for index in Appointment._meta.indexes], [("slot", "status")])


@skipIf(not is_postgres, "Database constraint tests require PostgreSQL")
class AppointmentPostgreSQLConstraintTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="appt-db-owner",
            email="appt-db-owner@example.com",
            password="test-password",
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="APPT-DB-1",
            current_mileage=100,
        )
        self.service_type = ServiceType.objects.create(
            name="DB service",
            description="test",
            interval_km=1000,
            interval_months=3,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        start = timezone.now() + timedelta(days=1)
        self.slot = ServiceSlot.objects.create(
            start_time=start,
            end_time=start + timedelta(minutes=30),
            capacity=2,
        )

    def create_appointment(self, status=AppointmentStatus.PENDING):
        return Appointment.objects.create(
            vehicle=self.vehicle,
            service_type=self.service_type,
            slot=self.slot,
            status=status,
        )

    def test_duplicate_active_vehicle_and_slot_is_rejected(self):
        self.create_appointment()
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_appointment(AppointmentStatus.IN_PROGRESS)

    def test_terminal_appointments_do_not_block_later_active_booking(self):
        self.create_appointment(AppointmentStatus.COMPLETED)
        self.create_appointment(AppointmentStatus.CANCELLED)
        later = self.create_appointment(AppointmentStatus.PENDING)
        self.assertEqual(later.status, AppointmentStatus.PENDING)

    def test_status_membership_constraint_rejects_unknown_value(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.create_appointment("UNKNOWN")

    def test_service_slot_checks_reject_invalid_range_and_capacity(self):
        start = timezone.now()
        for values in (
            {"start_time": start, "end_time": start, "capacity": 1},
            {"start_time": start, "end_time": start + timedelta(minutes=1), "capacity": 0},
        ):
            with self.subTest(values=values):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        ServiceSlot.objects.create(**values)
