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
from unittest import skipIf
from unittest.mock import patch
from django.urls import reverse

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
from .selectors import get_available_service_slots
from .forms import AppointmentBookingForm, TechnicianAssignmentForm
from .services import (
    AppointmentBookingError,
    TechnicianAssignmentError,
    assign_technician,
    book_appointment,
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
