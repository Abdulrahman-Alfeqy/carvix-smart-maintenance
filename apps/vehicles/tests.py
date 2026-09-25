from html.parser import HTMLParser
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from unittest import skipIf

from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.appointments.models import Appointment, ServiceSlot
from apps.maintenance.models import MaintenanceRecord, ServiceType, TechnicianProfile

from .forms import VehicleForm
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


class VehicleWorkflowTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="workflow-owner",
            email="workflow-owner@example.com",
            password="test-password",
            role=User.Role.OWNER,
        )
        self.other_owner = User.objects.create_user(
            username="workflow-other-owner",
            email="workflow-other-owner@example.com",
            password="test-password",
            role=User.Role.OWNER,
        )
        self.technician = User.objects.create_user(
            username="workflow-technician",
            email="workflow-technician@example.com",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        self.administrator = User.objects.create_user(
            username="workflow-administrator",
            email="workflow-administrator@example.com",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Toyota",
            model="Corolla",
            model_year=2022,
            license_plate="OWNER-1",
            current_mileage=12000,
        )
        self.other_vehicle = Vehicle.objects.create(
            owner=self.other_owner,
            manufacturer="Honda",
            model="Civic",
            model_year=2020,
            license_plate="OTHER-1",
            current_mileage=30000,
        )

    def make_maintenance_record(
        self,
        vehicle,
        name,
        service_date,
        mileage,
        notes="",
        technician_username="workflow-maintenance-tech",
    ):
        service_type = ServiceType.objects.create(
            name=name,
            description="Test maintenance service",
            interval_km=5000,
            interval_months=6,
            duration_minutes=45,
            price=Decimal("25.00"),
        )
        tech_user, _ = User.objects.get_or_create(
            username=technician_username,
            defaults={
                "email": f"{technician_username}@example.com",
                "role": User.Role.TECHNICIAN,
            },
        )
        technician, _ = TechnicianProfile.objects.get_or_create(
            user=tech_user,
            defaults={"specialization": "General service"},
        )
        start = timezone.now() + timedelta(days=1)
        slot = ServiceSlot.objects.create(
            start_time=start,
            end_time=start + timedelta(minutes=45),
            capacity=1,
        )
        appointment = Appointment.objects.create(
            vehicle=vehicle,
            service_type=service_type,
            slot=slot,
            technician=technician,
        )
        return MaintenanceRecord.objects.create(
            vehicle=vehicle,
            service_type=service_type,
            technician=technician,
            appointment=appointment,
            service_date=service_date,
            mileage_at_service=mileage,
            notes=notes,
        )

    def valid_vehicle_data(self, **overrides):
        data = {
            "manufacturer": "Mazda",
            "model": "3",
            "model_year": "2019",
            "license_plate": "NEW-123",
            "current_mileage": "25000",
        }
        data.update(overrides)
        return data

    def test_anonymous_users_redirect_to_login_for_all_endpoints(self):
        urls = [
            reverse("vehicles:vehicle-list"),
            reverse("vehicles:vehicle-create"),
            reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]),
            reverse("vehicles:vehicle-update", args=[self.vehicle.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, f"{reverse('authentication:login')}?next={url}")

    def test_technicians_and_administrators_receive_403_on_all_owner_endpoints(self):
        endpoints = [
            reverse("vehicles:vehicle-list"),
            reverse("vehicles:vehicle-create"),
            reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]),
            reverse("vehicles:vehicle-update", args=[self.vehicle.pk]),
        ]
        for user in (self.technician, self.administrator):
            self.client.force_login(user)
            for url in endpoints:
                with self.subTest(role=user.role, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_owner_list_contains_only_vehicles_they_own(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("vehicles:vehicle-list"))
        self.assertEqual(response.status_code, 200)
        self.assertQuerySetEqual(response.context["vehicles"], [self.vehicle])
        self.assertNotContains(response, self.other_vehicle.license_plate)

    def test_owner_can_create_vehicle_with_server_bound_ownership(self):
        self.client.force_login(self.owner)
        data = self.valid_vehicle_data(
            owner=str(self.other_owner.pk),
            owner_id=str(self.other_owner.pk),
        )
        response = self.client.post(reverse("vehicles:vehicle-create"), data)
        self.assertRedirects(response, reverse("vehicles:vehicle-list"))
        created = Vehicle.objects.get(license_plate="NEW-123")
        self.assertEqual(created.owner, self.owner)

    def test_owner_can_view_vehicle_detail(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.vehicle.license_plate)

    def test_vehicle_detail_renders_history_and_due_service_details(self):
        self.vehicle.current_mileage = 6000
        self.vehicle.save(update_fields=["current_mileage"])
        record = self.make_maintenance_record(
            self.vehicle,
            "Oil service",
            date(2026, 3, 25),
            1000,
            "Changed oil and filter",
        )
        self.client.force_login(self.owner)
        with patch("apps.maintenance.services.timezone.localdate", return_value=date(2026, 9, 25)):
            response = self.client.get(reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["maintenance_history"], [record])
        result = response.context["due_services"][0]
        self.assertEqual(result.status, "DUE")
        self.assertEqual(result.last_service, record)
        self.assertContains(response, "Maintenance History")
        self.assertContains(response, "Due-Service Overview")
        self.assertContains(response, "Oil service")
        self.assertContains(response, "Changed oil and filter")
        self.assertContains(response, "workflow-maintenance-tech")
        self.assertContains(response, "Next due mileage")
        self.assertContains(response, "Next due date")
        self.assertContains(response, "Mileage: DUE")
        self.assertContains(response, "Date: DUE")

    def test_vehicle_detail_shows_no_history_for_each_service_type(self):
        ServiceType.objects.create(
            name="Brake service",
            description="Brakes",
            interval_km=10000,
            interval_months=12,
            duration_minutes=60,
            price=Decimal("0.00"),
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No maintenance history is recorded for this vehicle.")
        self.assertContains(response, "NO_HISTORY")
        self.assertContains(response, "No recorded maintenance history is available for this service.")

    def test_vehicle_detail_excludes_another_vehicles_and_owners_history(self):
        own_record = self.make_maintenance_record(
            self.vehicle, "Owner service", date(2026, 1, 1), 1000, "OWNED NOTE"
        )
        foreign_record = self.make_maintenance_record(
            self.other_vehicle,
            "Other service",
            date(2025, 2, 3),
            28765,
            "FOREIGN NOTE",
            technician_username="foreign-maintenance-tech",
        )
        self.client.force_login(self.owner)
        response = self.client.get(reverse("vehicles:vehicle-detail", args=[self.vehicle.pk]))
        self.assertEqual(response.context["maintenance_history"], [own_record])
        self.assertContains(response, "OWNED NOTE")
        # ServiceType is shared catalog data; only the foreign record is private.
        self.assertContains(response, "Other service")
        due_by_service = {
            result.service_type.name: result
            for result in response.context["due_services"]
        }
        self.assertEqual(due_by_service["Other service"].status, "NO_HISTORY")
        self.assertIsNone(due_by_service["Other service"].last_service)
        self.assertNotIn(foreign_record, response.context["maintenance_history"])
        self.assertNotContains(response, "FOREIGN NOTE")
        self.assertNotContains(response, "2025-02-03")
        self.assertNotContains(response, "28765")
        self.assertNotContains(response, "foreign-maintenance-tech")

    def test_cross_owner_detail_does_not_start_maintenance_loading(self):
        self.client.force_login(self.owner)
        with patch("apps.vehicles.views.get_vehicle_maintenance_overview") as overview:
            response = self.client.get(reverse("vehicles:vehicle-detail", args=[self.other_vehicle.pk]))
        self.assertEqual(response.status_code, 404)
        overview.assert_not_called()

    def test_owner_can_update_vehicle_without_changing_ownership(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("vehicles:vehicle-update", args=[self.vehicle.pk]),
            self.valid_vehicle_data(
                license_plate="UPDATED-1",
                owner=str(self.other_owner.pk),
                owner_id=str(self.other_owner.pk),
            ),
        )
        self.assertRedirects(response, reverse("vehicles:vehicle-list"))
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.owner, self.owner)
        self.assertEqual(self.vehicle.license_plate, "UPDATED-1")

    def test_cross_owner_detail_and_update_requests_return_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(reverse("vehicles:vehicle-detail", args=[self.other_vehicle.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("vehicles:vehicle-update", args=[self.other_vehicle.pk])).status_code,
            404,
        )

    def test_cross_owner_update_post_returns_404_without_side_effect(self):
        self.client.force_login(self.owner)
        original = (
            self.other_vehicle.manufacturer,
            self.other_vehicle.model,
            self.other_vehicle.model_year,
            self.other_vehicle.license_plate,
            self.other_vehicle.current_mileage,
            self.other_vehicle.owner_id,
        )
        response = self.client.post(
            reverse("vehicles:vehicle-update", args=[self.other_vehicle.pk]),
            self.valid_vehicle_data(
                license_plate="ATTACK-1",
                owner=str(self.owner.pk),
                owner_id=str(self.owner.pk),
            ),
        )
        self.assertEqual(response.status_code, 404)
        self.other_vehicle.refresh_from_db()
        self.assertEqual(
            (
                self.other_vehicle.manufacturer,
                self.other_vehicle.model,
                self.other_vehicle.model_year,
                self.other_vehicle.license_plate,
                self.other_vehicle.current_mileage,
                self.other_vehicle.owner_id,
            ),
            original,
        )

    def test_create_get_displays_unbound_form_without_creating_vehicle(self):
        self.client.force_login(self.owner)
        count = Vehicle.objects.count()
        response = self.client.get(reverse("vehicles:vehicle-create"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_bound)
        self.assertEqual(Vehicle.objects.count(), count)

    def test_update_get_does_not_change_vehicle_fields(self):
        self.client.force_login(self.owner)
        before = (
            self.vehicle.manufacturer,
            self.vehicle.model,
            self.vehicle.model_year,
            self.vehicle.license_plate,
            self.vehicle.current_mileage,
            self.vehicle.owner_id,
            self.vehicle.created_at,
        )
        response = self.client.get(reverse("vehicles:vehicle-update", args=[self.vehicle.pk]))
        self.assertEqual(response.status_code, 200)
        self.vehicle.refresh_from_db()
        self.assertEqual(
            (
                self.vehicle.manufacturer,
                self.vehicle.model,
                self.vehicle.model_year,
                self.vehicle.license_plate,
                self.vehicle.current_mileage,
                self.vehicle.owner_id,
                self.vehicle.created_at,
            ),
            before,
        )

    def test_vehicle_form_has_exact_allowlist(self):
        self.assertEqual(
            tuple(VehicleForm().fields),
            ("manufacturer", "model", "model_year", "license_plate", "current_mileage"),
        )
        self.assertNotIn("owner", VehicleForm().fields)
        self.assertNotIn("created_at", VehicleForm().fields)

    def test_duplicate_case_insensitive_plate_is_a_create_field_error(self):
        form = VehicleForm(data=self.valid_vehicle_data(license_plate="owner-1"))
        self.assertFalse(form.is_valid())
        self.assertIn("license_plate", form.errors)

    def test_duplicate_case_insensitive_plate_is_an_update_field_error(self):
        form = VehicleForm(
            instance=self.vehicle,
            data=self.valid_vehicle_data(license_plate="other-1"),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("license_plate", form.errors)

    def test_update_duplicate_validation_excludes_current_vehicle(self):
        form = VehicleForm(
            instance=self.vehicle,
            data=self.valid_vehicle_data(license_plate=self.vehicle.license_plate.lower()),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["license_plate"], self.vehicle.license_plate)

    def test_negative_mileage_is_a_field_error(self):
        form = VehicleForm(data=self.valid_vehicle_data(current_mileage="-1"))
        self.assertFalse(form.is_valid())
        self.assertIn("current_mileage", form.errors)

    def test_required_fields_have_field_specific_errors(self):
        form = VehicleForm(data={})
        self.assertFalse(form.is_valid())
        self.assertEqual(
            set(form.errors),
            {"manufacturer", "model", "model_year", "license_plate", "current_mileage"},
        )

    def test_plate_normalization_preserves_arabic_digits_and_internal_separators(self):
        data = self.valid_vehicle_data(license_plate="  ab-١٢٣ / ب  ")
        form = VehicleForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["license_plate"], "AB-١٢٣ / ب")

    def test_model_year_has_no_invented_range(self):
        form = VehicleForm(data=self.valid_vehicle_data(model_year="1900"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_owner_sees_vehicles_navigation_link(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("authentication:profile"))
        self.assertContains(response, f'href="{reverse("vehicles:vehicle-list")}">Vehicles</a>')

    def test_technician_and_administrator_do_not_see_owner_vehicles_link(self):
        for user in (self.technician, self.administrator):
            self.client.force_login(user)
            with self.subTest(role=user.role):
                response = self.client.get(reverse("authentication:profile"))
                self.assertNotContains(response, "Vehicles</a>")


class _CsrfInputParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        if tag != "input":
            return
        attributes = dict(attrs)
        if attributes.get("type") == "hidden" and attributes.get("name") == "csrfmiddlewaretoken":
            self.token = attributes.get("value")


@override_settings(ALLOWED_HOSTS=["testserver"])
class VehicleWorkflowCsrfTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="csrf-owner",
            email="csrf-owner@example.com",
            password="test-password",
            role=User.Role.OWNER,
        )
        self.vehicle = Vehicle.objects.create(
            owner=self.owner,
            manufacturer="Toyota",
            model="Corolla",
            model_year=2022,
            license_plate="CSRF-1",
            current_mileage=1000,
        )
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.owner)

    def valid_data(self, plate):
        return {
            "manufacturer": "Mazda",
            "model": "3",
            "model_year": "2019",
            "license_plate": plate,
            "current_mileage": "25000",
        }

    def rendered_csrf_token(self, response):
        parser = _CsrfInputParser()
        parser.feed(response.content.decode(response.charset))
        self.assertTrue(parser.token)
        self.assertIn("csrftoken", response.cookies)
        self.assertTrue(response.cookies["csrftoken"].value)
        return parser.token

    def test_create_post_without_csrf_token_is_rejected(self):
        response = self.client.post(reverse("vehicles:vehicle-create"), self.valid_data("CSRF-2"))
        self.assertEqual(response.status_code, 403)

    def test_update_post_without_csrf_token_is_rejected(self):
        response = self.client.post(
            reverse("vehicles:vehicle-update", args=[self.vehicle.pk]),
            self.valid_data("CSRF-UPDATED"),
        )
        self.assertEqual(response.status_code, 403)

    def test_create_csrf_round_trip_accepts_rendered_token(self):
        create_url = reverse("vehicles:vehicle-create")
        get_response = self.client.get(create_url)
        self.assertEqual(get_response.status_code, 200)
        token = self.rendered_csrf_token(get_response)
        data = self.valid_data("CSRF-CREATE")
        data["csrfmiddlewaretoken"] = token

        response = self.client.post(
            create_url,
            data,
        )
        self.assertNotEqual(response.status_code, 403)
        self.assertRedirects(response, reverse("vehicles:vehicle-list"))
        created = Vehicle.objects.get(license_plate="CSRF-CREATE")
        self.assertEqual(created.owner, self.owner)

    def test_update_csrf_round_trip_accepts_rendered_token(self):
        update_url = reverse("vehicles:vehicle-update", args=[self.vehicle.pk])
        get_response = self.client.get(update_url)
        self.assertEqual(get_response.status_code, 200)
        token = self.rendered_csrf_token(get_response)
        data = self.valid_data("CSRF-UPDATED")
        data["csrfmiddlewaretoken"] = token

        response = self.client.post(
            update_url,
            data,
        )
        self.assertNotEqual(response.status_code, 403)
        self.assertRedirects(response, reverse("vehicles:vehicle-list"))
        self.vehicle.refresh_from_db()
        self.assertEqual(self.vehicle.license_plate, "CSRF-UPDATED")
        self.assertEqual(self.vehicle.manufacturer, "Mazda")
        self.assertEqual(self.vehicle.current_mileage, 25000)
        self.assertEqual(self.vehicle.owner, self.owner)
