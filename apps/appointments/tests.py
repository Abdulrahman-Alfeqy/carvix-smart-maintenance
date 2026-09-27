from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.db.models.deletion import ProtectedError
from django.test import Client
from django.test.utils import CaptureQueriesContext
from unittest import skipIf
from unittest.mock import patch
from django.urls import reverse

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.inventory.models import SparePart
from apps.maintenance.models import (
    MaintenancePart,
    MaintenanceRecord,
    ServiceType,
    TechnicianProfile,
)
from apps.vehicles.models import Vehicle

from .models import (
    ACTIVE_APPOINTMENT_STATUSES,
    TERMINAL_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    ServiceSlot,
)
from .selectors import get_available_service_slots
from .forms import AppointmentBookingForm, TechnicianAssignmentForm
from .services import (
    AppointmentBookingError,
    TechnicianAssignmentError,
    TechnicianMaintenanceError,
    assign_technician,
    book_appointment,
    complete_appointment_maintenance,
    start_appointment_service,
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


class AvailableServiceSlotSelectorTests(AppointmentFixtures):
    def test_returns_only_active_future_slots_with_remaining_capacity(self):
        now = timezone.now()
        self.slot.is_active = False
        self.slot.save(update_fields=("is_active",))

        available = self.make_slot(
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
            capacity=2,
        )
        inactive = self.make_slot(
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=3),
            is_active=False,
        )
        started = self.make_slot(
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(minutes=29),
        )
        full = self.make_slot(
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=4),
            capacity=1,
        )
        self.make_appointment(slot=full)

        slots = list(get_available_service_slots())

        self.assertEqual([slot.pk for slot in slots], [available.pk])
        self.assertEqual(slots[0].active_appointment_count, 0)
        self.assertNotIn(inactive, slots)
        self.assertNotIn(started, slots)
        self.assertNotIn(full, slots)

    def test_capacity_counts_only_active_appointment_statuses_in_one_query(self):
        slot = self.make_slot(capacity=4)
        for index, status in enumerate(ACTIVE_APPOINTMENT_STATUSES):
            owner = User.objects.create_user(
                username=f"selector-owner-{index}",
                email=f"selector-owner-{index}@example.com",
                password="test-password",
            )
            vehicle = Vehicle.objects.create(
                owner=owner,
                manufacturer="Toyota",
                model="Yaris",
                model_year=2021,
                license_plate=f"SELECTOR-{index}",
                current_mileage=500,
            )
            self.make_appointment(vehicle=vehicle, slot=slot, status=status)

        terminal_slot = self.make_slot(capacity=1)
        self.make_appointment(slot=terminal_slot, status=AppointmentStatus.COMPLETED)
        self.make_appointment(slot=terminal_slot, status=AppointmentStatus.CANCELLED)

        with self.assertNumQueries(1):
            slots = list(get_available_service_slots())

        by_id = {available.pk: available for available in slots}
        self.assertEqual(by_id[slot.pk].active_appointment_count, 3)
        self.assertEqual(by_id[terminal_slot.pk].active_appointment_count, 0)


class AppointmentBookingFormTests(AppointmentFixtures):
    def test_vehicle_queryset_is_limited_to_the_owner_and_fields_are_allowlisted(self):
        other_owner = User.objects.create_user(
            username="booking-form-other",
            email="booking-form-other@example.com",
            password="test-password",
        )
        other_vehicle = Vehicle.objects.create(
            owner=other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="BOOK-FORM-OTHER",
            current_mileage=100,
        )

        form = AppointmentBookingForm(owner=self.owner, initial_vehicle=self.vehicle)

        self.assertEqual(list(form.fields["vehicle"].queryset), [self.vehicle])
        self.assertNotIn(other_vehicle, form.fields["vehicle"].queryset)
        self.assertEqual(set(form.fields), {"vehicle", "service_type", "slot"})
        self.assertIn(self.slot, form.fields["slot"].queryset)


class AppointmentBookingServiceTests(AppointmentFixtures):
    def book(self, **overrides):
        values = {
            "actor": self.owner,
            "vehicle_id": self.vehicle.pk,
            "service_type_id": self.service_type.pk,
            "slot_id": self.slot.pk,
        }
        values.update(overrides)
        return book_appointment(**values)

    def test_owner_booking_sets_only_manual_appointment_defaults(self):
        appointment = self.book()

        self.assertEqual(appointment.vehicle, self.vehicle)
        self.assertEqual(appointment.service_type, self.service_type)
        self.assertEqual(appointment.slot, self.slot)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertIsNone(appointment.technician)
        self.assertFalse(appointment.booked_by_agent)

    def test_anonymous_and_non_owner_actors_are_rejected(self):
        with self.assertRaises(AppointmentBookingError) as anonymous:
            self.book(actor=AnonymousUser())
        self.assertEqual(anonymous.exception.code, "permission_denied")

        with self.assertRaises(AppointmentBookingError) as technician:
            self.book(actor=self.tech_user)
        self.assertEqual(technician.exception.code, "permission_denied")
        self.assertEqual(Appointment.objects.count(), 0)

    def test_foreign_vehicle_is_rejected_without_disclosing_ownership(self):
        other_owner = User.objects.create_user(
            username="booking-service-other",
            email="booking-service-other@example.com",
            password="test-password",
        )
        other_vehicle = Vehicle.objects.create(
            owner=other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="BOOK-SVC-OTHER",
            current_mileage=100,
        )

        with self.assertRaises(AppointmentBookingError) as raised:
            self.book(vehicle_id=other_vehicle.pk)

        self.assertEqual(raised.exception.code, "permission_denied")
        self.assertNotIn(other_vehicle.license_plate, str(raised.exception))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_invalid_service_and_identifiers_are_rejected(self):
        for values, expected_code in (
            ({"service_type_id": 999999}, "invalid_service"),
            ({"slot_id": "not-an-id"}, "invalid_selection"),
        ):
            with self.subTest(values=values):
                with self.assertRaises(AppointmentBookingError) as raised:
                    self.book(**values)
                self.assertEqual(raised.exception.code, expected_code)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_inactive_and_started_slots_are_rejected(self):
        self.slot.is_active = False
        self.slot.save(update_fields=("is_active",))
        with self.assertRaises(AppointmentBookingError) as inactive:
            self.book()
        self.assertEqual(inactive.exception.code, "slot_inactive")

        self.slot.is_active = True
        self.slot.start_time = timezone.now() - timedelta(minutes=1)
        self.slot.end_time = timezone.now() + timedelta(minutes=29)
        self.slot.save(update_fields=("is_active", "start_time", "end_time"))
        with self.assertRaises(AppointmentBookingError) as started:
            self.book()
        self.assertEqual(started.exception.code, "slot_expired")
        self.assertEqual(Appointment.objects.count(), 0)

    def test_duplicate_and_full_slot_are_rejected(self):
        self.make_appointment(slot=self.slot)
        with self.assertRaises(AppointmentBookingError) as duplicate:
            self.book()
        self.assertEqual(duplicate.exception.code, "duplicate_booking")

        other_owner = User.objects.create_user(
            username="booking-capacity-owner",
            email="booking-capacity-owner@example.com",
            password="test-password",
        )
        other_vehicle = Vehicle.objects.create(
            owner=other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="BOOK-CAPACITY",
            current_mileage=100,
        )
        full_slot = self.make_slot(capacity=1)
        self.make_appointment(vehicle=other_vehicle, slot=full_slot)

        with self.assertRaises(AppointmentBookingError) as full:
            self.book(slot_id=full_slot.pk)
        self.assertEqual(full.exception.code, "slot_full")

    def test_terminal_appointments_do_not_consume_capacity(self):
        self.slot.capacity = 1
        self.slot.save(update_fields=("capacity",))
        self.make_appointment(status=AppointmentStatus.COMPLETED)
        self.make_appointment(status=AppointmentStatus.CANCELLED)

        appointment = self.book()

        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertEqual(
            Appointment.objects.filter(
                slot=self.slot,
                status__in=ACTIVE_APPOINTMENT_STATUSES,
            ).count(),
            1,
        )

    def test_expected_duplicate_constraint_error_is_translated_after_atomic_rollback(self):
        original_create = Appointment.objects.create

        def create_then_fail(**kwargs):
            original_create(**kwargs)
            error = IntegrityError("private database detail")
            database_error = Exception("driver detail")
            database_error.diag = SimpleNamespace(
                constraint_name="appointments_active_slot_vehicle_uniq"
            )
            error.__cause__ = database_error
            raise error

        with patch.object(Appointment.objects, "create", side_effect=create_then_fail):
            with self.assertRaises(AppointmentBookingError) as raised:
                self.book()

        self.assertEqual(raised.exception.code, "booking_conflict")
        self.assertNotIn("private database detail", str(raised.exception))
        self.assertEqual(Appointment.objects.count(), 0)

    def test_unrelated_integrity_error_propagates_after_atomic_rollback(self):
        original_create = Appointment.objects.create

        def create_then_fail(**kwargs):
            original_create(**kwargs)
            error = IntegrityError("unrelated private database detail")
            database_error = Exception("driver detail")
            database_error.diag = SimpleNamespace(
                constraint_name="appointments_status_valid"
            )
            error.__cause__ = database_error
            raise error

        with patch.object(Appointment.objects, "create", side_effect=create_then_fail):
            with self.assertRaisesRegex(IntegrityError, "unrelated private database detail"):
                self.book()

        self.assertEqual(Appointment.objects.count(), 0)


class AppointmentBookingViewTests(AppointmentFixtures):
    def setUp(self):
        super().setUp()
        self.url = reverse("appointments:book", kwargs={"vehicle_pk": self.vehicle.pk})

    def test_owner_can_open_booking_form_from_owned_vehicle(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Book a Service")
        self.assertContains(response, str(self.vehicle.license_plate))
        self.assertContains(response, "csrfmiddlewaretoken")

    def test_other_owner_vehicle_is_not_retrieved(self):
        other_owner = User.objects.create_user(
            username="booking-view-other",
            email="booking-view-other@example.com",
            password="test-password",
        )
        other_vehicle = Vehicle.objects.create(
            owner=other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="BOOK-VIEW-OTHER",
            current_mileage=100,
        )
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("appointments:book", kwargs={"vehicle_pk": other_vehicle.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_anonymous_and_non_owner_access_are_denied(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

        self.client.force_login(self.tech_user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_administrator_access_is_denied(self):
        administrator = User.objects.create_user(
            username="booking-admin",
            email="booking-admin@example.com",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.client.force_login(administrator)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_form_rendering_makes_final_booking_action_explicit(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertContains(response, "Confirm and Book Appointment")
        self.assertContains(response, "Submitting this form will create the appointment.")
        self.assertNotContains(response, "Review Selection")

    def test_valid_post_persists_and_confirms_the_saved_appointment(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            {
                "vehicle": str(self.vehicle.pk),
                "service_type": str(self.service_type.pk),
                "slot": str(self.slot.pk),
                "status": "COMPLETED",
                "booked_by_agent": "true",
                "technician": str(self.technician.pk),
            },
        )

        appointment = Appointment.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("vehicles:vehicle-detail", kwargs={"pk": self.vehicle.pk}),
        )
        self.assertEqual(appointment.vehicle, self.vehicle)
        self.assertEqual(appointment.service_type, self.service_type)
        self.assertEqual(appointment.slot, self.slot)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertIsNone(appointment.technician)
        self.assertFalse(appointment.booked_by_agent)
        self.assertContains(self.client.get(response.url), f"Appointment {appointment.pk} booked")

    def test_invalidated_slot_returns_safe_error_and_creates_no_appointment(self):
        self.slot.is_active = False
        self.slot.save(update_fields=("is_active",))
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            {
                "vehicle": str(self.vehicle.pk),
                "service_type": str(self.service_type.pk),
                "slot": str(self.slot.pk),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "time slot is no longer available")
        self.assertEqual(Appointment.objects.count(), 0)

    def test_csrf_is_required_for_post(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)

        response = csrf_client.post(
            self.url,
            {
                "vehicle": str(self.vehicle.pk),
                "service_type": str(self.service_type.pk),
                "slot": str(self.slot.pk),
            },
        )

        self.assertEqual(response.status_code, 403)


class AdministratorAssignmentViewTests(AppointmentFixtures):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("appointments:administrator-assignment-list")

    def create_administrator(self):
        return User.objects.create_user(
            username="assignment-admin",
            email="assignment-admin@example.com",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
            is_staff=False,
            is_superuser=False,
        )

    def assignment_url(self, appointment):
        return reverse(
            "appointments:administrator-appointment-assign",
            kwargs={"appointment_pk": appointment.pk},
        )

    def test_anonymous_requests_redirect_to_login(self):
        appointment = self.make_appointment(technician=None)
        for url in (self.list_url, self.assignment_url(appointment)):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("authentication:login"), response.url)

    def test_only_domain_administrator_can_access_endpoints(self):
        appointment = self.make_appointment(technician=None)
        self.owner.is_staff = True
        self.owner.save(update_fields=("is_staff",))
        self.tech_user.is_staff = True
        self.tech_user.save(update_fields=("is_staff",))

        for user in (self.owner, self.tech_user):
            self.client.force_login(user)
            for method, url in (
                ("get", self.list_url),
                ("get", self.assignment_url(appointment)),
                ("post", self.assignment_url(appointment)),
            ):
                with self.subTest(role=user.role, method=method, url=url):
                    response = getattr(self.client, method)(url)
                    self.assertEqual(response.status_code, 403)

        administrator = self.create_administrator()
        self.client.force_login(administrator)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.assignment_url(appointment)).status_code, 200)

    def test_get_is_read_only_and_lists_only_unassigned_appointments(self):
        appointment = self.make_appointment(technician=None, status=AppointmentStatus.CONFIRMED)
        assigned = self.make_appointment(
            slot=self.make_slot(), technician=self.technician
        )
        administrator = self.create_administrator()
        self.client.force_login(administrator)

        list_response = self.client.get(self.list_url)
        form_response = self.client.get(self.assignment_url(appointment))

        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, f"Appointment {appointment.pk}")
        self.assertNotContains(list_response, f"Appointment {assigned.pk}")
        self.assertEqual(form_response.status_code, 200)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.technician_id)
        self.assertEqual(appointment.status, AppointmentStatus.CONFIRMED)

    def test_nonexistent_or_already_assigned_appointment_is_not_assignable(self):
        administrator = self.create_administrator()
        self.client.force_login(administrator)

        self.assertEqual(
            self.client.get(
                reverse(
                    "appointments:administrator-appointment-assign",
                    kwargs={"appointment_pk": 999999},
                )
            ).status_code,
            404,
        )

        assigned = self.make_appointment(technician=self.technician)
        self.assertEqual(self.client.get(self.assignment_url(assigned)).status_code, 404)
        with self.assertRaises(TechnicianAssignmentError) as raised:
            assign_technician(
                actor=administrator,
                appointment_id=assigned.pk,
                technician_profile_id=self.technician.pk,
            )
        self.assertEqual(raised.exception.code, "already_assigned")

    def test_csrf_is_required_for_assignment_post(self):
        appointment = self.make_appointment(technician=None)
        administrator = self.create_administrator()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(administrator)

        response = csrf_client.post(
            self.assignment_url(appointment),
            {
                "technician": str(self.technician.pk),
                "confirm_assignment": "on",
            },
        )

        self.assertEqual(response.status_code, 403)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.technician_id)

    def test_confirmed_csrf_post_assigns_only_technician_and_preserves_other_fields(self):
        appointment = self.make_appointment(
            technician=None,
            status=AppointmentStatus.IN_PROGRESS,
            notes="preserve these appointment notes",
            booked_by_agent=True,
        )
        original_values = {
            "vehicle_id": appointment.vehicle_id,
            "service_type_id": appointment.service_type_id,
            "slot_id": appointment.slot_id,
            "status": appointment.status,
            "notes": appointment.notes,
            "booked_by_agent": appointment.booked_by_agent,
        }
        administrator = self.create_administrator()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(administrator)
        form_response = csrf_client.get(self.assignment_url(appointment))
        csrf_token = form_response.cookies["csrftoken"].value

        self.assertEqual(form_response.status_code, 200)
        self.assertContains(form_response, "Confirm Assignment")
        response = csrf_client.post(
            self.assignment_url(appointment),
            {
                "technician": str(self.technician.pk),
                "confirm_assignment": "on",
                "csrfmiddlewaretoken": csrf_token,
                "user_id": "999999",
                "administrator_id": "999999",
                "status": AppointmentStatus.COMPLETED,
            },
        )

        self.assertEqual(response.status_code, 302)
        appointment.refresh_from_db()
        self.assertEqual(appointment.technician_id, self.technician.pk)
        for field, value in original_values.items():
            self.assertEqual(getattr(appointment, field), value)

    def test_owner_and_administrator_profiles_are_rejected_as_technicians(self):
        administrator = self.create_administrator()
        owner_profile = TechnicianProfile.objects.create(
            user=self.owner,
            specialization="Invalid Owner profile",
        )
        administrator_profile = TechnicianProfile.objects.create(
            user=administrator,
            specialization="Invalid Administrator profile",
        )

        for profile in (owner_profile, administrator_profile):
            with self.subTest(role=profile.user.role):
                with self.assertRaises(TechnicianAssignmentError) as raised:
                    assign_technician(
                        actor=administrator,
                        appointment_id=self.make_appointment(
                            slot=self.make_slot(), technician=None
                        ).pk,
                        technician_profile_id=profile.pk,
                    )
                self.assertEqual(raised.exception.code, "invalid_technician")

    def test_unavailable_and_nonexistent_technician_profiles_are_rejected(self):
        administrator = self.create_administrator()
        appointment = self.make_appointment(technician=None)
        self.technician.is_available = False
        self.technician.save(update_fields=("is_available",))

        for profile_id in (self.technician.pk, 999999, "invalid"):
            with self.subTest(profile_id=profile_id):
                with self.assertRaises(TechnicianAssignmentError):
                    assign_technician(
                        actor=administrator,
                        appointment_id=appointment.pk,
                        technician_profile_id=profile_id,
                    )
                appointment.refresh_from_db()
                self.assertIsNone(appointment.technician_id)

    def test_assignment_requires_domain_administrator_even_with_forged_role_fields(self):
        appointment = self.make_appointment(technician=None)
        self.client.force_login(self.owner)

        response = self.client.post(
            self.assignment_url(appointment),
            {
                "technician": str(self.technician.pk),
                "confirm_assignment": "on",
                "role": User.Role.ADMINISTRATOR,
                "is_superuser": "true",
            },
        )

        self.assertEqual(response.status_code, 403)
        appointment.refresh_from_db()
        self.assertIsNone(appointment.technician_id)


class OwnerAppointmentViewTests(AppointmentFixtures):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("appointments:appointment-list")

    def create_other_owner_appointment(self):
        other_owner = User.objects.create_user(
            username="list-other-owner",
            email="list-other-owner@example.com",
            password="test-password",
        )
        other_vehicle = Vehicle.objects.create(
            owner=other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="LIST-OTHER-OWNER",
            current_mileage=100,
        )
        return self.make_appointment(
            vehicle=other_vehicle,
            status=AppointmentStatus.CANCELLED,
            notes="private other-owner appointment note",
        )

    def test_anonymous_list_and_detail_requests_redirect_to_login(self):
        detail_url = reverse(
            "appointments:appointment-detail", kwargs={"pk": self.make_appointment().pk}
        )
        for url in (self.list_url, detail_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("authentication:login"), response.url)

    def test_technician_and_administrator_receive_403_on_list_and_detail(self):
        appointment = self.make_appointment()
        detail_url = reverse(
            "appointments:appointment-detail", kwargs={"pk": appointment.pk}
        )
        administrator = User.objects.create_user(
            username="appointment-view-admin",
            email="appointment-view-admin@example.com",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )

        for user in (self.tech_user, administrator):
            self.client.force_login(user)
            for url in (self.list_url, detail_url):
                with self.subTest(user=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_owner_list_contains_only_owned_appointments_in_model_order(self):
        earlier = self.make_appointment(
            status=AppointmentStatus.CANCELLED,
            notes="owner earlier appointment",
        )
        later = self.make_appointment(
            slot=self.make_slot(),
            status=AppointmentStatus.CANCELLED,
            notes="owner later appointment",
        )
        foreign = self.create_other_owner_appointment()
        self.client.force_login(self.owner)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(response.context["appointments"]), [later, earlier]
        )
        self.assertContains(response, f"Appointment {earlier.pk}")
        self.assertContains(response, f"Appointment {later.pk}")
        self.assertNotContains(response, f"Appointment {foreign.pk}")
        self.assertNotContains(response, foreign.notes)

    def test_owner_with_no_appointments_sees_empty_state_and_no_foreign_rows(self):
        foreign = self.create_other_owner_appointment()
        self.client.force_login(self.owner)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You do not have any appointments yet.")
        self.assertEqual(list(response.context["appointments"]), [])
        self.assertNotContains(response, f"Appointment {foreign.pk}")
        self.assertNotContains(
            response,
            reverse("appointments:appointment-detail", kwargs={"pk": foreign.pk}),
        )
        self.assertNotContains(response, foreign.notes)

    def test_owner_can_view_own_detail_and_query_owner_id_does_not_change_scope(self):
        appointment = self.make_appointment(notes="owner appointment detail note")
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("appointments:appointment-detail", kwargs={"pk": appointment.pk}),
            {"owner_id": "999999"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["appointment"], appointment)
        self.assertContains(response, appointment.vehicle.license_plate)
        self.assertContains(response, appointment.service_type.name)
        self.assertContains(response, appointment.notes)

    def test_detail_renders_assigned_technician_without_disclosing_user_data(self):
        appointment = self.make_appointment()
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("appointments:appointment-detail", kwargs={"pk": appointment.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<dt>Technician</dt>", html=True)
        self.assertContains(response, f"<dd>{self.tech_user.username}</dd>", html=True)
        self.assertNotContains(response, self.tech_user.email)
        self.assertNotContains(response, User.Role.TECHNICIAN)
        self.assertNotContains(response, "is_staff")
        self.assertNotContains(response, "is_superuser")
        self.assertNotContains(response, "Permissions")
        self.assertNotContains(response, "Technician ID")
        self.assertNotContains(response, "User ID")

    def test_detail_shows_neutral_fallback_when_no_technician_is_assigned(self):
        appointment = self.make_appointment(technician=None)
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("appointments:appointment-detail", kwargs={"pk": appointment.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<dt>Technician</dt>", html=True)
        self.assertContains(response, "<dd>Not assigned</dd>", html=True)

    def test_cross_owner_detail_returns_404_without_disclosing_appointment_data(self):
        foreign = self.create_other_owner_appointment()
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("appointments:appointment-detail", kwargs={"pk": foreign.pk})
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, foreign.vehicle.license_plate, status_code=404)
        self.assertNotContains(response, foreign.notes, status_code=404)

    def test_read_only_endpoints_reject_post_and_get_does_not_mutate(self):
        appointment = self.make_appointment()
        detail_url = reverse(
            "appointments:appointment-detail", kwargs={"pk": appointment.pk}
        )
        original_status = appointment.status
        self.client.force_login(self.owner)

        for url in (self.list_url, detail_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)

        self.client.get(self.list_url)
        self.client.get(detail_url)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, original_status)
        self.assertEqual(Appointment.objects.count(), 1)


class TechnicianAppointmentViewTests(AppointmentFixtures):
    def setUp(self):
        super().setUp()
        self.list_url = reverse("appointments:technician-appointment-list")

    def detail_url(self, appointment):
        return reverse(
            "appointments:technician-appointment-detail",
            kwargs={"pk": appointment.pk},
        )

    def create_technician(self, username):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        return TechnicianProfile.objects.create(user=user, specialization="General")

    def test_anonymous_list_and_detail_redirect_to_login(self):
        appointment = self.make_appointment()
        for url in (self.list_url, self.detail_url(appointment)):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("authentication:login"), response.url)

    def test_only_technician_role_can_access_assigned_endpoints(self):
        appointment = self.make_appointment()
        administrator = User.objects.create_user(
            username="technician-view-admin",
            email="technician-view-admin@example.com",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        for user in (self.owner, administrator):
            self.client.force_login(user)
            for url in (self.list_url, self.detail_url(appointment)):
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.tech_user)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(self.detail_url(appointment)).status_code, 200)

    def test_technician_without_profile_is_rejected_safely(self):
        user = User.objects.create_user(
            username="technician-without-profile",
            email="technician-without-profile@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        self.client.force_login(user)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

    def test_list_contains_only_current_assignments_in_model_order(self):
        older = self.make_appointment(notes="current technician older appointment")
        newer = self.make_appointment(
            slot=self.make_slot(), notes="current technician newer appointment"
        )
        foreign_technician = self.create_technician("other-assigned-technician")
        foreign = self.make_appointment(
            slot=self.make_slot(),
            technician=foreign_technician,
            notes="foreign technician private appointment",
        )
        unassigned = self.make_appointment(
            slot=self.make_slot(), technician=None, notes="unassigned private appointment"
        )
        self.client.force_login(self.tech_user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["appointments"]), [newer, older])
        self.assertContains(response, f"Appointment {newer.pk}")
        self.assertContains(response, f"Appointment {older.pk}")
        for excluded in (foreign, unassigned):
            self.assertNotContains(response, f"Appointment {excluded.pk}")
            self.assertNotContains(response, excluded.notes)

    def test_list_has_clear_empty_state(self):
        self.make_appointment(technician=None)
        self.client.force_login(self.tech_user)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no assigned appointments.")
        self.assertEqual(list(response.context["appointments"]), [])

    def test_list_uses_one_joined_appointment_query(self):
        self.make_appointment()
        self.client.force_login(self.tech_user)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        appointment_queries = [
            query["sql"]
            for query in captured.captured_queries
            if 'FROM "appointments_appointment"' in query["sql"]
        ]
        self.assertEqual(len(appointment_queries), 1)
        for table in (
            '"vehicles_vehicle"',
            '"maintenance_servicetype"',
            '"appointments_serviceslot"',
        ):
            self.assertIn(table, appointment_queries[0])

    def test_detail_renders_assigned_appointment_safely(self):
        appointment = self.make_appointment(
            notes="Service note <script>window.leak = true</script>"
        )
        self.client.force_login(self.tech_user)

        response = self.client.get(self.detail_url(appointment))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["appointment"], appointment)
        self.assertContains(response, appointment.vehicle.license_plate)
        self.assertContains(response, appointment.service_type.name)
        self.assertContains(response, "Service note")
        self.assertContains(response, "&lt;script&gt;window.leak = true&lt;/script&gt;")
        self.assertNotContains(response, "<script>")
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, self.tech_user.email)
        self.assertNotContains(response, "is_staff")
        self.assertNotContains(response, "is_superuser")

    def test_detail_shows_fallback_when_notes_are_missing(self):
        appointment = self.make_appointment(notes="")
        self.client.force_login(self.tech_user)

        response = self.client.get(self.detail_url(appointment))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No appointment notes.")

    def test_other_technician_unassigned_and_missing_appointments_return_404(self):
        other_profile = self.create_technician("other-detail-technician")
        other_appointment = self.make_appointment(
            slot=self.make_slot(),
            technician=other_profile,
            notes="other technician private note",
        )
        unassigned = self.make_appointment(slot=self.make_slot(), technician=None)
        self.client.force_login(self.tech_user)

        for appointment_id in (other_appointment.pk, unassigned.pk, 999999):
            with self.subTest(appointment_id=appointment_id):
                response = self.client.get(
                    reverse(
                        "appointments:technician-appointment-detail",
                        kwargs={"pk": appointment_id},
                    )
                )
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(
                    response,
                    "other technician private note",
                    status_code=404,
                )

    def test_read_only_endpoints_reject_post_and_get_does_not_mutate(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        status = appointment.status
        count = Appointment.objects.count()
        self.client.force_login(self.tech_user)

        for url in (self.list_url, self.detail_url(appointment)):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 405)
                self.assertEqual(self.client.get(url).status_code, 200)

        appointment.refresh_from_db()
        self.assertEqual(appointment.status, status)
        self.assertEqual(Appointment.objects.count(), count)


class TechnicianMaintenanceWorkflowTests(AppointmentFixtures):
    def detail_url(self, appointment):
        return reverse(
            "appointments:technician-appointment-detail",
            kwargs={"pk": appointment.pk},
        )

    def create_technician(self, username):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        return TechnicianProfile.objects.create(user=user, specialization="General")

    def start_url(self, appointment):
        return reverse("appointments:technician-appointment-start", kwargs={"pk": appointment.pk})

    def completion_url(self, appointment):
        return reverse("appointments:technician-appointment-complete", kwargs={"pk": appointment.pk})

    def part(self, **overrides):
        values = {
            "name": "Oil filter",
            "part_number": "MAINT-FILTER",
            "quantity": 10,
            "minimum_stock": 1,
            "unit_price": Decimal("5.25"),
        }
        values.update(overrides)
        return SparePart.objects.create(**values)

    def completion_data(self, *, mileage=550, notes="Oil and filter changed", usages=(), **extra):
        data = {
            "mileage_at_service": str(mileage),
            "notes": notes,
            "parts-TOTAL_FORMS": "10",
            "parts-INITIAL_FORMS": "0",
            "parts-MIN_NUM_FORMS": "0",
            "parts-MAX_NUM_FORMS": "20",
        }
        for index, (part, quantity) in enumerate(usages):
            data[f"parts-{index}-spare_part"] = str(part.pk if hasattr(part, "pk") else part)
            data[f"parts-{index}-quantity_used"] = str(quantity)
        data.update(extra)
        return data

    def test_start_service_allows_only_pending_and_confirmed(self):
        self.client.force_login(self.tech_user)
        for status in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
            with self.subTest(source=status):
                appointment = self.make_appointment(slot=self.make_slot(), status=status)
                response = self.client.post(self.start_url(appointment))
                self.assertRedirects(response, self.detail_url(appointment))
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)

    def test_start_service_rejects_in_progress_completed_and_cancelled_without_other_changes(self):
        self.client.force_login(self.tech_user)
        for status in (
            AppointmentStatus.IN_PROGRESS,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
        ):
            with self.subTest(source=status):
                appointment = self.make_appointment(
                    slot=self.make_slot(), status=status, notes="preserve these notes"
                )
                response = self.client.post(self.start_url(appointment))
                self.assertRedirects(response, self.detail_url(appointment))
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, status)
                self.assertEqual(appointment.notes, "preserve these notes")

    def test_start_service_is_post_only_csrf_protected_and_get_is_read_only(self):
        appointment = self.make_appointment()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.tech_user)
        response = client.get(self.start_url(appointment))
        self.assertEqual(response.status_code, 405)
        response = client.post(self.start_url(appointment))
        self.assertEqual(response.status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)

        detail = client.get(self.detail_url(appointment))
        token = detail.cookies["csrftoken"].value
        response = client.post(self.start_url(appointment), {"csrfmiddlewaretoken": token})
        self.assertRedirects(response, self.detail_url(appointment))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)

    def test_start_service_authorization_and_assignment_isolation(self):
        appointment = self.make_appointment()
        another_tech = self.create_technician("start-other-tech")
        foreign = self.make_appointment(slot=self.make_slot(), technician=another_tech)
        unassigned = self.make_appointment(slot=self.make_slot(), technician=None)
        url = self.start_url(appointment)
        self.assertEqual(self.client.post(url).status_code, 302)

        admin = User.objects.create_user(
            username="start-admin", email="start-admin@example.com",
            password="test-password", role=User.Role.ADMINISTRATOR,
        )
        for user in (self.owner, admin):
            self.client.force_login(user)
            self.assertEqual(self.client.post(url).status_code, 403)

        no_profile = User.objects.create_user(
            username="start-no-profile", email="start-no-profile@example.com",
            password="test-password", role=User.Role.TECHNICIAN,
        )
        self.client.force_login(no_profile)
        self.assertEqual(self.client.post(url).status_code, 403)

        self.client.force_login(self.tech_user)
        for hidden in (foreign, unassigned):
            response = self.client.post(self.start_url(hidden))
            self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(self.start_url(self.make_appointment(slot=self.make_slot(), technician=None))).status_code, 404)
        self.assertEqual(Appointment.objects.get(pk=foreign.pk).status, AppointmentStatus.PENDING)

    def test_start_service_revalidates_status_after_lock(self):
        appointment = self.make_appointment()
        Appointment.objects.filter(pk=appointment.pk).update(status=AppointmentStatus.CANCELLED)
        with self.assertRaises(TechnicianMaintenanceError) as raised:
            start_appointment_service(actor=self.tech_user, appointment_id=appointment.pk)
        self.assertEqual(raised.exception.code, "invalid_status")
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.CANCELLED)

    def test_completion_form_get_is_read_only_and_assignment_scoped(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        self.client.force_login(self.tech_user)
        response = self.client.get(self.completion_url(appointment))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertEqual(response.context["parts_formset"].total_form_count(), 10)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertEqual(MaintenanceRecord.objects.count(), 0)

        another_tech = self.create_technician("completion-other-tech")
        foreign = self.make_appointment(slot=self.make_slot(), technician=another_tech)
        self.assertEqual(self.client.get(self.completion_url(foreign)).status_code, 404)
        self.assertEqual(self.client.get(self.completion_url(self.make_appointment(slot=self.make_slot(), technician=None))).status_code, 404)
        self.assertEqual(self.client.get(reverse("appointments:technician-appointment-complete", kwargs={"pk": 999999})).status_code, 404)

    def test_completion_requires_technician_role_and_profile(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        url = self.completion_url(appointment)
        self.assertEqual(self.client.get(url).status_code, 302)
        for user in (self.owner,):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.completion_data()).status_code, 403)
        administrator = User.objects.create_user(
            username="complete-admin", email="complete-admin@example.com",
            password="test-password", role=User.Role.ADMINISTRATOR,
        )
        self.client.force_login(administrator)
        self.assertEqual(self.client.get(url).status_code, 403)

        no_profile = User.objects.create_user(
            username="complete-no-profile", email="complete-no-profile@example.com",
            password="test-password", role=User.Role.TECHNICIAN,
        )
        self.client.force_login(no_profile)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, self.completion_data()).status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertFalse(appointment.maintenance_records.exists())

    def test_completion_only_accepts_in_progress_status(self):
        self.client.force_login(self.tech_user)
        for status in (
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
            AppointmentStatus.COMPLETED,
            AppointmentStatus.CANCELLED,
        ):
            with self.subTest(status=status):
                appointment = self.make_appointment(slot=self.make_slot(), status=status)
                response = self.client.post(
                    self.completion_url(appointment),
                    self.completion_data(mileage=600),
                )
                self.assertEqual(response.status_code, 200)
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, status)
                self.assertFalse(appointment.maintenance_records.exists())

    def test_completion_requires_post_and_csrf(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.tech_user)
        self.assertEqual(client.get(self.completion_url(appointment)).status_code, 200)
        self.assertEqual(client.post(self.completion_url(appointment), self.completion_data()).status_code, 403)
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertFalse(appointment.maintenance_records.exists())

        token = client.cookies["csrftoken"].value
        response = client.post(
            self.completion_url(appointment),
            self.completion_data(mileage=560, csrfmiddlewaretoken=token),
        )
        self.assertRedirects(response, self.detail_url(appointment))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.COMPLETED)

    def test_completion_derives_relationships_and_ignores_forged_ids(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        other_vehicle = Vehicle.objects.create(
            owner=self.owner, manufacturer="Honda", model="Civic", model_year=2020,
            license_plate="FORGED-VEHICLE", current_mileage=100,
        )
        other_tech = self.create_technician("forged-tech")
        self.client.force_login(self.tech_user)
        response = self.client.post(
            self.completion_url(appointment),
            self.completion_data(
                mileage=600, notes="Recorded work",
                vehicle=str(other_vehicle.pk), technician=str(other_tech.pk),
                appointment="999999", owner_id="999999", user_id="999999",
            ),
        )
        self.assertRedirects(response, self.detail_url(appointment))
        record = MaintenanceRecord.objects.get(appointment=appointment)
        self.assertEqual(record.vehicle, appointment.vehicle)
        self.assertEqual(record.service_type, appointment.service_type)
        self.assertEqual(record.technician, self.technician)
        self.assertEqual(record.mileage_at_service, 600)
        self.assertEqual(record.notes, "Recorded work")
        self.assertEqual(record.service_date, timezone.localdate())
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.COMPLETED)

    def test_completion_without_parts_and_with_multiple_parts(self):
        self.client.force_login(self.tech_user)
        without_parts = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        response = self.client.post(self.completion_url(without_parts), self.completion_data(mileage=550))
        self.assertRedirects(response, self.detail_url(without_parts))
        self.assertEqual(without_parts.maintenance_records.count(), 1)
        self.assertEqual(without_parts.maintenance_records.get().maintenance_parts.count(), 0)

        with_parts = self.make_appointment(slot=self.make_slot(), status=AppointmentStatus.IN_PROGRESS)
        first = self.part(part_number="MULTI-1", quantity=5)
        second = self.part(name="Oil", part_number="MULTI-2", quantity=4)
        response = self.client.post(
            self.completion_url(with_parts),
            self.completion_data(mileage=560, usages=((first, 2), (second, 4))),
        )
        self.assertRedirects(response, self.detail_url(with_parts))
        record = with_parts.maintenance_records.get()
        self.assertEqual(set(record.maintenance_parts.values_list("spare_part_id", flat=True)), {first.pk, second.pk})
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.quantity, 3)
        self.assertEqual(second.quantity, 0)

    def test_invalid_parts_and_mileage_leave_everything_unchanged(self):
        self.client.force_login(self.tech_user)
        scenarios = (
            ("duplicate", lambda part: ((part, 1), (part, 2))),
            ("missing", lambda _part: ((999999, 1),)),
            ("zero", lambda part: ((part, 0),)),
            ("negative", lambda part: ((part, -1),)),
            ("malformed", lambda part: ((part, "1.5"),)),
            ("insufficient", lambda part: ((part, 11),)),
        )
        for index, (name, usage_factory) in enumerate(scenarios):
            with self.subTest(name=name):
                appointment = self.make_appointment(
                    slot=self.make_slot(), status=AppointmentStatus.IN_PROGRESS
                )
                part = self.part(part_number=f"INVALID-{index}")
                usages = usage_factory(part)
                response = self.client.post(
                    self.completion_url(appointment),
                    self.completion_data(mileage=550, usages=usages),
                )
                self.assertEqual(response.status_code, 200)
                appointment.refresh_from_db()
                part.refresh_from_db()
                self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
                self.assertFalse(appointment.maintenance_records.exists())
                self.assertEqual(part.quantity, 10)
                self.assertEqual(MaintenancePart.objects.count(), 0)

    def test_negative_and_malformed_mileage_are_rejected(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        self.client.force_login(self.tech_user)
        for value in ("-1", "not-a-number", "1.5"):
            with self.subTest(mileage=value):
                response = self.client.post(
                    self.completion_url(appointment),
                    self.completion_data(mileage=value),
                )
                self.assertEqual(response.status_code, 200)
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
                self.assertFalse(appointment.maintenance_records.exists())

    def test_lower_mileage_rejected_and_stock_never_partially_changes(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        first = self.part(part_number="ROLLBACK-1", quantity=8)
        second = self.part(part_number="ROLLBACK-2", quantity=1)
        self.client.force_login(self.tech_user)
        response = self.client.post(
            self.completion_url(appointment),
            self.completion_data(mileage=499, usages=((first, 3), (second, 2))),
        )
        self.assertEqual(response.status_code, 200)
        appointment.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertEqual(first.quantity, 8)
        self.assertEqual(second.quantity, 1)
        self.assertFalse(appointment.maintenance_records.exists())
        self.assertEqual(MaintenancePart.objects.count(), 0)

    def test_direct_service_rejects_non_integral_and_invalid_mileage_without_side_effects(self):
        part = self.part(part_number="MILEAGE-INVALID", quantity=9)
        rejected_values = (550.9, -0.5, True, "not-a-number", -1)

        for index, value in enumerate(rejected_values):
            with self.subTest(mileage=value):
                appointment = self.make_appointment(
                    slot=self.make_slot(), status=AppointmentStatus.IN_PROGRESS
                )
                with self.assertRaises(TechnicianMaintenanceError) as raised:
                    complete_appointment_maintenance(
                        actor=self.tech_user,
                        appointment_id=appointment.pk,
                        mileage_at_service=value,
                        notes="Invalid mileage must not persist",
                        parts=((part.pk, 1),),
                    )
                self.assertEqual(raised.exception.code, "invalid_mileage")
                appointment.refresh_from_db()
                part.refresh_from_db()
                self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
                self.assertFalse(appointment.maintenance_records.exists())
                self.assertEqual(MaintenancePart.objects.count(), 0)
                self.assertEqual(part.quantity, 9)

    def test_direct_service_accepts_integer_and_decimal_free_integer_string(self):
        for index, value in enumerate((551, "552")):
            with self.subTest(mileage=value):
                appointment = self.make_appointment(
                    slot=self.make_slot(), status=AppointmentStatus.IN_PROGRESS
                )
                record = complete_appointment_maintenance(
                    actor=self.tech_user,
                    appointment_id=appointment.pk,
                    mileage_at_service=value,
                )
                self.assertEqual(record.mileage_at_service, 551 + index)
                appointment.refresh_from_db()
                self.assertEqual(appointment.status, AppointmentStatus.COMPLETED)

    def test_direct_service_rejects_fractional_decimal_without_side_effects(self):
        from decimal import Decimal

        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        part = self.part(part_number="MILEAGE-DECIMAL", quantity=4)
        with self.assertRaises(TechnicianMaintenanceError) as raised:
            complete_appointment_maintenance(
                actor=self.tech_user,
                appointment_id=appointment.pk,
                mileage_at_service=Decimal("550.9"),
                parts=((part.pk, 2),),
            )
        self.assertEqual(raised.exception.code, "invalid_mileage")
        appointment.refresh_from_db()
        part.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertFalse(appointment.maintenance_records.exists())
        self.assertEqual(MaintenancePart.objects.count(), 0)
        self.assertEqual(part.quantity, 4)

    def test_unexpected_failure_after_record_creation_rolls_back_all_writes(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        first = self.part(part_number="FAIL-A", quantity=8)
        second = self.part(part_number="FAIL-B", quantity=8)
        from apps.appointments import services

        real_create = MaintenancePart.objects.create
        calls = 0

        def fail_on_second_part(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("simulated persistence failure")
            return real_create(*args, **kwargs)

        with patch.object(services.MaintenancePart.objects, "create", side_effect=fail_on_second_part):
            with self.assertRaises(RuntimeError):
                complete_appointment_maintenance(
                    actor=self.tech_user,
                    appointment_id=appointment.pk,
                    mileage_at_service=550,
                    notes="Must roll back",
                    parts=((first.pk, 2), (second.pk, 3)),
                )

        appointment.refresh_from_db()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(appointment.status, AppointmentStatus.IN_PROGRESS)
        self.assertFalse(appointment.maintenance_records.exists())
        self.assertEqual(MaintenancePart.objects.count(), 0)
        self.assertEqual((first.quantity, second.quantity), (8, 8))

    def test_completed_appointment_cannot_be_completed_twice(self):
        appointment = self.make_appointment(status=AppointmentStatus.IN_PROGRESS)
        self.client.force_login(self.tech_user)
        self.assertEqual(self.client.post(self.completion_url(appointment), self.completion_data()).status_code, 302)
        response = self.client.post(self.completion_url(appointment), self.completion_data())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(appointment.maintenance_records.count(), 1)


@skipIf(not is_postgres, "Concurrent booking tests require PostgreSQL row locks")
class AppointmentBookingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owners = [
            User.objects.create_user(
                username=f"concurrent-owner-{index}",
                email=f"concurrent-owner-{index}@example.com",
                password="test-password",
            )
            for index in range(2)
        ]
        self.vehicles = [
            Vehicle.objects.create(
                owner=owner,
                manufacturer="Toyota",
                model="Yaris",
                model_year=2021,
                license_plate=f"CONCURRENT-{index}",
                current_mileage=500,
            )
            for index, owner in enumerate(self.owners)
        ]
        self.service_type = ServiceType.objects.create(
            name="Concurrent booking service",
            description="Test service",
            interval_km=1000,
            interval_months=3,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        start = timezone.now() + timedelta(days=1)
        self.slot = ServiceSlot.objects.create(
            start_time=start,
            end_time=start + timedelta(minutes=30),
            capacity=1,
        )

    def test_concurrent_different_owners_cannot_exceed_slot_capacity(self):
        barrier = Barrier(2)

        def attempt_booking(index):
            close_old_connections()
            try:
                owner = User.objects.get(pk=self.owners[index].pk)
                barrier.wait(timeout=10)
                appointment = book_appointment(
                    actor=owner,
                    vehicle_id=self.vehicles[index].pk,
                    service_type_id=self.service_type.pk,
                    slot_id=self.slot.pk,
                )
                return ("booked", appointment.pk)
            except AppointmentBookingError as error:
                return ("rejected", error.code)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(attempt_booking, range(2)))

        self.assertCountEqual([outcome[0] for outcome in outcomes], ["booked", "rejected"])
        rejected = next(outcome for outcome in outcomes if outcome[0] == "rejected")
        self.assertEqual(rejected[1], "slot_full")
        self.assertEqual(
            Appointment.objects.filter(
                slot=self.slot,
                status__in=ACTIVE_APPOINTMENT_STATUSES,
            ).count(),
            1,
        )


@skipIf(not is_postgres, "Concurrent completion tests require PostgreSQL row locks")
class TechnicianCompletionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="completion-concurrency-owner",
            email="completion-concurrency-owner@example.com",
            password="test-password",
        )
        tech_user = User.objects.create_user(
            username="completion-concurrency-tech",
            email="completion-concurrency-tech@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        self.technician = TechnicianProfile.objects.create(
            user=tech_user, specialization="General"
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Toyota",
            model="Yaris",
            model_year=2021,
            license_plate="CONCURRENT-COMPLETE",
            current_mileage=500,
        )
        self.service_type = ServiceType.objects.create(
            name="Concurrent completion service",
            description="Test service",
            interval_km=1000,
            interval_months=3,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        slot = ServiceSlot.objects.create(
            start_time=timezone.now() + timedelta(days=1),
            end_time=timezone.now() + timedelta(days=1, minutes=30),
            capacity=1,
        )
        self.appointment = Appointment.objects.create(
            vehicle=self.vehicle,
            service_type=self.service_type,
            slot=slot,
            technician=self.technician,
            status=AppointmentStatus.IN_PROGRESS,
        )
        self.part = SparePart.objects.create(
            name="Concurrent filter",
            part_number="CONCURRENT-FILTER",
            quantity=1,
            minimum_stock=0,
            unit_price=Decimal("5.00"),
        )
        self.tech_user_id = tech_user.pk

    def test_concurrent_completion_creates_one_record_and_consumes_stock_once(self):
        barrier = Barrier(2)

        def attempt_completion():
            close_old_connections()
            try:
                actor = User.objects.get(pk=self.tech_user_id)
                barrier.wait(timeout=10)
                record = complete_appointment_maintenance(
                    actor=actor,
                    appointment_id=self.appointment.pk,
                    mileage_at_service=550,
                    notes="Concurrent completion",
                    parts=[(self.part.pk, 1)],
                )
                return ("completed", record.pk)
            except TechnicianMaintenanceError as error:
                return ("rejected", error.code)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _index: attempt_completion(), range(2)))

        self.assertCountEqual([outcome[0] for outcome in outcomes], ["completed", "rejected"])
        self.assertEqual(
            Appointment.objects.get(pk=self.appointment.pk).status,
            AppointmentStatus.COMPLETED,
        )
        self.assertEqual(MaintenanceRecord.objects.filter(appointment=self.appointment).count(), 1)
        self.assertEqual(MaintenancePart.objects.count(), 1)
        self.part.refresh_from_db()
        self.assertEqual(self.part.quantity, 0)


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
