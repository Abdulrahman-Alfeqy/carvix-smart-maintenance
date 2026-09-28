import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment, ServiceSlot
from apps.maintenance.models import ServiceType
from apps.vehicles.models import Vehicle

from .booking_tool import TOOL_NAME, book_maintenance_appointment
from .maintenance_tool import check_required_maintenance
from .models import AgentActionLog
from .slot_tool import list_available_service_slots
from .tools import TOOL_REGISTRY


User = get_user_model()


class ReadToolFixtures(TestCase):
    def setUp(self):
        self.owner = self.make_user("read-owner", User.Role.OWNER)
        self.other_owner = self.make_user("read-other", User.Role.OWNER)
        self.technician = self.make_user("read-tech", User.Role.TECHNICIAN)
        self.administrator = self.make_user("read-admin", User.Role.ADMINISTRATOR)
        self.vehicle = self.make_vehicle(self.owner, "READ-1")
        self.other_vehicle = self.make_vehicle(self.other_owner, "READ-2")
        self.service_type = self.make_service_type()

    def make_user(self, username, role):
        return User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="safe-test-password",
            role=role,
        )

    def make_vehicle(self, owner, plate):
        return Vehicle.objects.create(
            owner=owner,
            manufacturer="Toyota",
            model="Corolla",
            model_year=2022,
            license_plate=plate,
            current_mileage=12000,
        )

    def make_service_type(self, name="Oil service"):
        return ServiceType.objects.create(
            name=name,
            description="Routine oil service",
            interval_km=5000,
            interval_months=6,
            duration_minutes=45,
            price=Decimal("25.00"),
        )

    def make_slot(self, *, start_time=None, capacity=2, is_active=True):
        start_time = start_time or timezone.now() + timedelta(days=2)
        return ServiceSlot.objects.create(
            start_time=start_time,
            end_time=start_time + timedelta(minutes=45),
            capacity=capacity,
            is_active=is_active,
        )

    def call_maintenance(self, actor=None, arguments=None):
        return check_required_maintenance(
            actor=self.owner if actor is None else actor,
            arguments={"vehicle_id": self.vehicle.pk} if arguments is None else arguments,
        )

    def call_slots(self, actor=None, arguments=None):
        return list_available_service_slots(
            actor=self.owner if actor is None else actor,
            arguments={"service_type_id": self.service_type.pk} if arguments is None else arguments,
        )


class CheckRequiredMaintenanceToolTests(ReadToolFixtures):
    def test_owner_uses_existing_overview_and_receives_json_safe_no_history(self):
        from apps.maintenance.services import get_vehicle_maintenance_overview

        with patch(
            "apps.ai_agent.maintenance_tool.get_vehicle_maintenance_overview",
            wraps=get_vehicle_maintenance_overview,
        ) as overview_service:
            result = self.call_maintenance()

        overview_service.assert_called_once_with(self.vehicle)
        self.assertEqual(set(result), {"success", "code", "message", "data", "errors"})
        self.assertTrue(result["success"])
        self.assertIsNone(result["errors"])
        self.assertEqual(result["data"]["vehicle_id"], self.vehicle.pk)
        self.assertEqual(result["data"]["services"][0]["status"], "NO_HISTORY")
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_maintenance_results_serialize_only_required_due_data(self):
        service_result = type(
            "DueResult",
            (),
            {
                "service_type": self.service_type,
                "status": "DUE",
                "last_service": type(
                    "LastService",
                    (),
                    {"service_date": timezone.localdate(), "mileage_at_service": 7000},
                )(),
                "next_due_mileage": 12000,
                "next_due_date": timezone.localdate() + timedelta(days=1),
                "reason": "Mileage: DUE.",
            },
        )()
        with patch(
            "apps.ai_agent.maintenance_tool.get_vehicle_maintenance_overview",
            return_value={"history": [], "due_services": [service_result]},
        ):
            result = self.call_maintenance()

        serialized = result["data"]["services"][0]
        self.assertEqual(serialized["status"], "DUE")
        self.assertEqual(serialized["service_type"]["name"], self.service_type.name)
        self.assertEqual(serialized["last_service"]["mileage_at_service"], 7000)
        self.assertNotIn("notes", json.dumps(result).casefold())
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_only_authenticated_owner_can_check_maintenance(self):
        for actor in (AnonymousUser(), self.technician, self.administrator):
            with self.subTest(actor=actor):
                with patch(
                    "apps.ai_agent.maintenance_tool.get_vehicle_maintenance_overview"
                ) as overview_service:
                    result = self.call_maintenance(actor=actor)
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], "permission_denied")
                overview_service.assert_not_called()

    def test_foreign_or_missing_vehicle_is_safe_and_service_is_not_called(self):
        for vehicle_id in (self.other_vehicle.pk, 999999):
            with self.subTest(vehicle_id=vehicle_id):
                with patch(
                    "apps.ai_agent.maintenance_tool.get_vehicle_maintenance_overview"
                ) as overview_service:
                    result = self.call_maintenance(arguments={"vehicle_id": vehicle_id})
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], "vehicle_unavailable")
                self.assertNotIn(str(vehicle_id), json.dumps(result))
                overview_service.assert_not_called()
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_bad_or_extra_vehicle_arguments_are_rejected(self):
        for arguments in (
            {},
            {"vehicle_id": True},
            {"vehicle_id": 0},
            {"vehicle_id": -1},
            {"vehicle_id": "١٢"},
            {"vehicle_id": "9" * 1000},
            {"vehicle_id": 1.5},
            {"vehicle_id": self.vehicle.pk, "user_id": self.owner.pk},
        ):
            with self.subTest(arguments=arguments):
                result = self.call_maintenance(arguments=arguments)
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], "invalid_arguments")
                self.assertIsNone(result["data"])

    def test_unexpected_service_error_is_sanitized(self):
        with patch(
            "apps.ai_agent.maintenance_tool.get_vehicle_maintenance_overview",
            side_effect=RuntimeError("database password=secret"),
        ):
            result = self.call_maintenance()
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "maintenance_unavailable")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(AgentActionLog.objects.count(), 0)


class ListAvailableServiceSlotsToolTests(ReadToolFixtures):
    def test_srs_roles_reuse_selector_and_return_json_safe_global_availability(self):
        from apps.appointments.selectors import get_available_service_slots

        available = self.make_slot(capacity=3)
        self.make_slot(capacity=1, start_time=timezone.now() + timedelta(days=3))
        full = ServiceSlot.objects.order_by("-start_time").first()
        Appointment.objects.create(
            vehicle=self.vehicle,
            service_type=self.service_type,
            slot=full,
        )
        inactive = self.make_slot(is_active=False)
        started = self.make_slot(
            start_time=timezone.now() - timedelta(minutes=5),
        )

        for actor in (self.owner, self.technician, self.administrator):
            with self.subTest(role=actor.role):
                with patch(
                    "apps.ai_agent.slot_tool.get_available_service_slots",
                    wraps=get_available_service_slots,
                ) as slot_selector:
                    result = self.call_slots(actor=actor)
                slot_selector.assert_called_once_with()
                self.assertTrue(result["success"])
                ids = [item["id"] for item in result["data"]["slots"]]
                self.assertIn(available.pk, ids)
                self.assertNotIn(full.pk, ids)
                self.assertNotIn(inactive.pk, ids)
                self.assertNotIn(started.pk, ids)
                self.assertEqual(
                    next(item for item in result["data"]["slots"] if item["id"] == available.pk)[
                        "remaining_capacity"
                    ],
                    3,
                )
                self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_valid_preferred_date_is_strictly_validated_but_does_not_filter(self):
        first = self.make_slot()
        second = self.make_slot(start_time=timezone.now() + timedelta(days=4))
        result = self.call_slots(
            arguments={
                "service_type_id": self.service_type.pk,
                "preferred_date": "2020-02-29",
            }
        )
        self.assertTrue(result["success"])
        self.assertIn("filtering is not available", result["message"])
        self.assertEqual(
            {slot["id"] for slot in result["data"]["slots"]},
            {first.pk, second.pk},
        )

    def test_malformed_or_invalid_calendar_dates_are_rejected_before_selector(self):
        for value in ("2026-2-01", "2026-02-30", "2024-02-31", "2026-01-01T00:00:00", 20260101):
            with self.subTest(value=value):
                with patch("apps.ai_agent.slot_tool.get_available_service_slots") as selector:
                    result = self.call_slots(
                        arguments={
                            "service_type_id": self.service_type.pk,
                            "preferred_date": value,
                        }
                    )
                self.assertFalse(result["success"])
                self.assertEqual(result["errors"].keys(), {"preferred_date"})
                selector.assert_not_called()

    def test_slot_tool_requires_authenticated_supported_domain_role(self):
        for actor in (AnonymousUser(), type("UnknownActor", (), {"is_authenticated": True, "role": "UNKNOWN"})()):
            with self.subTest(actor=actor):
                with patch("apps.ai_agent.slot_tool.get_available_service_slots") as selector:
                    result = self.call_slots(actor=actor)
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], "permission_denied")
                selector.assert_not_called()

    def test_service_identifier_is_validated_before_selector_and_has_no_relation_claim(self):
        with patch("apps.ai_agent.slot_tool.get_available_service_slots") as selector:
            missing = self.call_slots(arguments={"service_type_id": 999999})
        self.assertFalse(missing["success"])
        self.assertEqual(missing["code"], "invalid_service")
        selector.assert_not_called()

        result = self.call_slots()
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["service_type"]["id"], self.service_type.pk)
        self.assertNotIn("service_type_id", result["data"]["slots"][0] if result["data"]["slots"] else {})

    def test_malformed_slot_arguments_are_rejected_and_no_agent_logs_are_written(self):
        for arguments in (
            {},
            {"service_type_id": True},
            {"service_type_id": 0},
            {"service_type_id": "abc"},
            {"service_type_id": "9" * 1000},
            {"service_type_id": self.service_type.pk, "vehicle_id": self.vehicle.pk},
        ):
            with self.subTest(arguments=arguments):
                result = self.call_slots(arguments=arguments)
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], "invalid_arguments")
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_selector_failure_is_safe(self):
        with patch(
            "apps.ai_agent.slot_tool.get_available_service_slots",
            side_effect=RuntimeError("password=secret"),
        ):
            result = self.call_slots()
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "slots_unavailable")
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(AgentActionLog.objects.count(), 0)


class ReadToolBoundaryTests(ReadToolFixtures):
    def test_read_tools_remain_unregistered_beside_the_booking_tool(self):
        self.assertEqual(tuple(TOOL_REGISTRY), (TOOL_NAME,))
        self.assertIs(TOOL_REGISTRY[TOOL_NAME], book_maintenance_appointment)
        self.assertNotIn("check_required_maintenance", TOOL_REGISTRY)
        self.assertNotIn("list_available_service_slots", TOOL_REGISTRY)
