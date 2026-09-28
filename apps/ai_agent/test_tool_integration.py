"""Fake Provider coverage for the complete, audited CARVIX Tool loop."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase
from django.utils import timezone

from apps.ai_agent.agent import MAX_TOOL_ROUNDS, respond_to_message
from apps.ai_agent.booking_tool import TOOL_NAME
from apps.ai_agent.models import AgentActionLog
from apps.ai_agent.provider import ProviderReply
from apps.ai_agent.tool_schemas import TOOL_SCHEMAS
from apps.ai_agent.tools import TOOL_REGISTRY
from apps.appointments.models import Appointment, ServiceSlot
from apps.maintenance.models import MaintenanceRecord, ServiceType
from apps.vehicles.models import Vehicle


User = get_user_model()
APPROVED_TOOL_NAMES = {
    "check_required_maintenance",
    "list_available_service_slots",
    "book_maintenance_appointment",
}
OBSERVATION_KEYS = {"tool_name", "success", "code", "message", "data", "errors"}
CHAT_RESULT_KEYS = {"success", "code", "message", "data", "errors"}


class FakeProvider:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def generate(self, *, message, system_prompt, context):
        self.calls.append(
            {
                "message": message,
                "system_prompt": system_prompt,
                "context": json.loads(json.dumps(context)),
            }
        )
        if not self.replies:
            raise AssertionError("The Agent requested more Provider turns than the Fake Provider supplied.")
        return self.replies.pop(0)


class ToolIntegrationFixtures(TestCase):
    def setUp(self):
        self.owner = self.make_user("integration-owner")
        self.other_owner = self.make_user("integration-other")
        self.technician = self.make_user("integration-tech", User.Role.TECHNICIAN)
        self.administrator = self.make_user("integration-admin", User.Role.ADMINISTRATOR)
        self.service = ServiceType.objects.create(
            name="Integration service",
            description="End-to-end test service",
            interval_km=5000,
            interval_months=6,
            duration_minutes=45,
            price=Decimal("25.00"),
        )
        self.vehicle = self.make_vehicle(self.owner, "INT-OWN")
        self.foreign_vehicle = self.make_vehicle(self.other_owner, "INT-OTHER")
        self.slot = self.make_slot()

    def make_user(self, username, role=User.Role.OWNER):
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

    def make_slot(self, *, capacity=2, is_active=True, start_time=None):
        start_time = start_time or timezone.now() + timedelta(days=2)
        return ServiceSlot.objects.create(
            start_time=start_time,
            end_time=start_time + timedelta(minutes=45),
            capacity=capacity,
            is_active=is_active,
        )

    def booking_arguments(self, **overrides):
        values = {
            "vehicle_id": self.vehicle.pk,
            "service_type_id": self.service.pk,
            "slot_id": self.slot.pk,
            "confirmation": True,
        }
        values.update(overrides)
        return values

    def run_fake(self, provider, *, user=None, message="Help with my vehicle"):
        with patch("apps.ai_agent.agent.get_provider", return_value=provider):
            return respond_to_message(user=user or self.owner, message=message)

    def assert_observation(self, call_index, *, name, success):
        context = self.provider_context(call_index)
        self.assertEqual(len(context["tool_observations"]), 1)
        observation = context["tool_observations"][0]
        self.assertEqual(set(observation), OBSERVATION_KEYS)
        self.assertEqual(observation["tool_name"], name)
        self.assertIs(observation["success"], success)
        self.assertEqual(json.loads(json.dumps(observation)), observation)
        self.assertNotIn("actor", observation)
        self.assertNotIn("traceback", json.dumps(observation).casefold())
        self.assertNotIn("password", json.dumps(observation).casefold())
        return observation

    def provider_context(self, call_index):
        return self.fake.calls[call_index]["context"]


class ToolSchemaAndDirectResponseTests(ToolIntegrationFixtures):
    def test_registry_and_schema_maps_contain_exact_approved_tool_names(self):
        self.assertEqual(set(TOOL_REGISTRY), APPROVED_TOOL_NAMES)
        self.assertEqual(set(TOOL_SCHEMAS), APPROVED_TOOL_NAMES)
        self.assertEqual(
            set(TOOL_SCHEMAS["check_required_maintenance"]["parameters"]["properties"]),
            {"vehicle_id"},
        )
        self.assertEqual(
            set(TOOL_SCHEMAS["list_available_service_slots"]["parameters"]["properties"]),
            {"service_type_id", "preferred_date"},
        )
        self.assertEqual(
            set(TOOL_SCHEMAS[TOOL_NAME]["parameters"]["properties"]),
            {"vehicle_id", "service_type_id", "slot_id", "confirmation"},
        )
        for schema in TOOL_SCHEMAS.values():
            self.assertFalse(schema["parameters"]["additionalProperties"])
            self.assertNotIn("user_id", json.dumps(schema))
            self.assertNotIn("owner_id", json.dumps(schema))
            self.assertNotIn("role", schema["parameters"]["properties"])
            self.assertEqual(json.loads(json.dumps(schema)), schema)

    def test_direct_final_response_has_no_tool_execution_or_audit(self):
        self.fake = FakeProvider(ProviderReply(text="Your vehicle records are ready to review."))

        result = self.run_fake(self.fake)

        self.assertEqual(set(result.__dataclass_fields__), CHAT_RESULT_KEYS)
        self.assertTrue(result.success)
        self.assertEqual(result.data, {"assistant_message": "Your vehicle records are ready to review."})
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(set(self.fake.calls[0]["context"]["tool_schemas"][0]), {"name", "description", "parameters"})
        self.assertEqual(self.fake.calls[0]["context"]["tool_observations"], [])
        self.assertEqual(AgentActionLog.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_provider_cannot_claim_booking_success_without_backend_booking_result(self):
        self.fake = FakeProvider(ProviderReply(text="Your appointment is booked successfully."))

        result = self.run_fake(self.fake)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "unverified_action_claim")
        self.assertNotIn("booked successfully", result.data["assistant_message"])
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_generic_completion_cannot_satisfy_a_booking_request_without_tool_result(self):
        self.fake = FakeProvider(ProviderReply(text="Done."))

        result = self.run_fake(self.fake, message="Book an appointment for my vehicle.")

        self.assertFalse(result.success)
        self.assertEqual(result.code, "unverified_action_claim")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 0)


class MaintenanceToolLoopTests(ToolIntegrationFixtures):
    def test_owner_maintenance_observation_returns_to_provider_before_final_text(self):
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={
                    "name": "check_required_maintenance",
                    "arguments": {"vehicle_id": self.vehicle.pk},
                }
            ),
            ProviderReply(text="The maintenance check found no recorded service history."),
        )
        appointment_count = Appointment.objects.count()
        maintenance_count = MaintenanceRecord.objects.count()

        result = self.run_fake(self.fake)

        self.assertTrue(result.success)
        self.assertEqual(result.data["assistant_message"], "The maintenance check found no recorded service history.")
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(self.provider_context(0)["tool_observations"], [])
        observation = self.assert_observation(
            1, name="check_required_maintenance", success=True
        )
        self.assertEqual(observation["data"]["vehicle_id"], self.vehicle.pk)
        self.assertEqual(result.data["tool_results"], [observation])
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().user, self.owner)
        self.assertEqual(Appointment.objects.count(), appointment_count)
        self.assertEqual(MaintenanceRecord.objects.count(), maintenance_count)

    def test_cross_owner_failure_is_audited_and_provider_success_claim_is_ignored(self):
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={
                    "name": "check_required_maintenance",
                    "arguments": {"vehicle_id": self.foreign_vehicle.pk},
                }
            ),
            ProviderReply(text="The other owner's car has overdue maintenance; I checked it."),
        )

        result = self.run_fake(self.fake)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "vehicle_unavailable")
        self.assertNotIn("other owner's car", result.message)
        observation = self.assert_observation(
            1, name="check_required_maintenance", success=False
        )
        self.assertEqual(observation["code"], "vehicle_unavailable")
        self.assertEqual(AgentActionLog.objects.count(), 1)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.status, AgentActionLog.Status.FAILURE)
        self.assertEqual(log.user, self.owner)
        self.assertEqual(Appointment.objects.count(), 0)


class SlotToolLoopTests(ToolIntegrationFixtures):
    def test_provider_can_select_the_named_service_from_server_context(self):
        class CatalogSelectingProvider:
            def __init__(self):
                self.calls = []

            def generate(self, *, message, system_prompt, context):
                safe_context = json.loads(json.dumps(context))
                self.calls.append(safe_context)
                if len(self.calls) == 1:
                    selected = next(
                        item for item in safe_context["service_types"]
                        if item["name"] == "Integration service"
                    )
                    return ProviderReply(
                        tool_call={
                            "name": "list_available_service_slots",
                            "arguments": {"service_type_id": selected["id"]},
                        }
                    )
                return ProviderReply(text="Eligible slots are available for that service.")

        provider = CatalogSelectingProvider()

        result = self.run_fake(
            provider,
            message="Find an available slot for Integration service",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(
            provider.calls[0]["service_types"],
            [{"id": self.service.pk, "name": "Integration service"}],
        )
        observation = provider.calls[1]["tool_observations"][0]
        self.assertTrue(observation["success"])
        self.assertEqual(
            observation["data"]["service_type"],
            {"id": self.service.pk, "name": "Integration service"},
        )

    def test_slot_observation_preserves_plan_017_global_and_preferred_date_contract(self):
        full_slot = self.make_slot(capacity=1, start_time=timezone.now() + timedelta(days=4))
        full_vehicle = self.make_vehicle(self.owner, "INT-FULL")
        Appointment.objects.create(
            vehicle=full_vehicle,
            service_type=self.service,
            slot=full_slot,
        )
        inactive_slot = self.make_slot(
            is_active=False,
            start_time=timezone.now() + timedelta(days=5),
        )
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={
                    "name": "list_available_service_slots",
                    "arguments": {
                        "service_type_id": self.service.pk,
                        "preferred_date": "2026-10-01",
                    },
                }
            ),
            ProviderReply(text="One eligible global slot is available."),
        )
        appointments_before = Appointment.objects.count()

        result = self.run_fake(self.fake, user=self.technician)

        self.assertTrue(result.success)
        self.assertEqual(
            [schema["name"] for schema in self.provider_context(0)["tool_schemas"]],
            ["list_available_service_slots"],
        )
        observation = self.assert_observation(
            1, name="list_available_service_slots", success=True
        )
        self.assertEqual(
            [slot["id"] for slot in observation["data"]["slots"]],
            [self.slot.pk],
        )
        self.assertIn("filtering is not available", observation["message"])
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().user, self.technician)
        self.assertEqual(Appointment.objects.count(), appointments_before)
        self.assertNotIn(inactive_slot.pk, [slot["id"] for slot in observation["data"]["slots"]])


class BookingToolLoopTests(ToolIntegrationFixtures):
    def test_confirmed_booking_round_trip_uses_authenticated_actor_and_returns_final_text(self):
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={
                    "name": TOOL_NAME,
                    "arguments": self.booking_arguments(),
                }
            ),
            ProviderReply(text="Your appointment is booked successfully."),
        )

        result = self.run_fake(self.fake)

        self.assertTrue(result.success)
        self.assertEqual(result.code, "ok")
        self.assertEqual(result.data["assistant_message"], "Your appointment is booked successfully.")
        observation = self.assert_observation(1, name=TOOL_NAME, success=True)
        self.assertEqual(observation["code"], "ok")
        self.assertEqual(Appointment.objects.count(), 1)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.vehicle, self.vehicle)
        self.assertTrue(appointment.booked_by_agent)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.user, self.owner)
        self.assertEqual(
            log.result,
            {key: observation[key] for key in ("success", "code", "message", "data", "errors")},
        )

    def test_missing_and_false_confirmation_never_book_even_if_provider_claims_success(self):
        for arguments in (
            {key: value for key, value in self.booking_arguments().items() if key != "confirmation"},
            self.booking_arguments(confirmation=False),
        ):
            with self.subTest(arguments=arguments):
                self.fake = FakeProvider(
                    ProviderReply(tool_call={"name": TOOL_NAME, "arguments": arguments}),
                    ProviderReply(text="The appointment has been booked successfully."),
                )
                result = self.run_fake(self.fake)

                self.assertFalse(result.success)
                self.assertEqual(result.code, "confirmation_required")
                self.assertEqual(Appointment.objects.count(), 0)
                self.assertEqual(AgentActionLog.objects.count(), 1)
                self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)
                self.assertNotIn("booked successfully", result.data["assistant_message"])
                AgentActionLog.objects.all().delete()

    def test_non_owner_booking_request_is_denied_and_audited(self):
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
            ProviderReply(text="The appointment was booked successfully."),
        )

        result = self.run_fake(self.fake, user=self.technician)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "permission_denied")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().user, self.technician)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_full_and_duplicate_slots_return_backend_failure_observations(self):
        full_slot = self.make_slot(capacity=1, start_time=timezone.now() + timedelta(days=5))
        full_vehicle = self.make_vehicle(self.owner, "INT-FULL-BOOKING")
        Appointment.objects.create(
            vehicle=full_vehicle,
            service_type=self.service,
            slot=full_slot,
        )
        full_arguments = self.booking_arguments(slot_id=full_slot.pk)
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": full_arguments}),
            ProviderReply(text="The appointment was booked successfully."),
        )

        full_result = self.run_fake(self.fake)

        self.assertFalse(full_result.success)
        self.assertEqual(full_result.code, "slot_unavailable")
        self.assertEqual(self.assert_observation(1, name=TOOL_NAME, success=False)["code"], "slot_unavailable")
        AgentActionLog.objects.all().delete()

        Appointment.objects.create(
            vehicle=self.vehicle,
            service_type=self.service,
            slot=self.slot,
        )
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
            ProviderReply(text="The appointment was booked successfully."),
        )

        duplicate_result = self.run_fake(self.fake)

        self.assertFalse(duplicate_result.success)
        self.assertEqual(duplicate_result.code, "duplicate_booking")
        self.assertEqual(
            self.assert_observation(1, name=TOOL_NAME, success=False)["code"],
            "duplicate_booking",
        )
        self.assertEqual(Appointment.objects.count(), 2)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_booking_handler_exception_is_contained_without_leaking_details(self):
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
            ProviderReply(text="The appointment was booked successfully."),
        )
        with patch(
            "apps.ai_agent.booking_tool.book_appointment",
            side_effect=RuntimeError("secret database password"),
        ):
            result = self.run_fake(self.fake)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "internal_error")
        self.assertNotIn("secret", json.dumps(result.data).casefold())
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_booking_cannot_repeat_with_different_arguments_after_success(self):
        second_slot = self.make_slot(start_time=timezone.now() + timedelta(days=8))
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
            ProviderReply(
                tool_call={
                    "name": TOOL_NAME,
                    "arguments": self.booking_arguments(slot_id=second_slot.pk),
                }
            ),
        )

        result = self.run_fake(self.fake)

        self.assertTrue(result.success)
        self.assertIn("No additional booking was created", result.data["assistant_message"])
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().tool_name, TOOL_NAME)

    def test_successful_booking_and_audit_roll_back_together_on_audit_failure(self):
        self.fake = FakeProvider(
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
            ProviderReply(text="The appointment succeeded."),
        )
        with patch.object(
            AgentActionLog.objects,
            "create",
            side_effect=OperationalError("private database detail"),
        ):
            result = self.run_fake(self.fake)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "internal_error")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 0)
        self.assertNotIn("private database", json.dumps(result.data))


class ToolLoopGuardTests(ToolIntegrationFixtures):
    def test_identical_read_request_is_not_dispatched_twice(self):
        request = {
            "name": "check_required_maintenance",
            "arguments": {"vehicle_id": self.vehicle.pk},
        }
        self.fake = FakeProvider(
            ProviderReply(tool_call=request),
            ProviderReply(tool_call=request),
        )

        result = self.run_fake(self.fake)

        self.assertTrue(result.success)
        self.assertEqual(len(self.fake.calls), 2)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().tool_name, "check_required_maintenance")

    def test_tool_failure_stops_later_side_effect_in_same_turn(self):
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={
                    "name": "check_required_maintenance",
                    "arguments": {"vehicle_id": self.foreign_vehicle.pk},
                }
            ),
            ProviderReply(tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}),
        )

        result = self.run_fake(self.fake)

        self.assertFalse(result.success)
        self.assertEqual(result.code, "vehicle_unavailable")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().tool_name, "check_required_maintenance")

    def test_unknown_multiple_malformed_and_blank_provider_outputs_do_not_execute(self):
        replies = (
            ProviderReply(tool_call={"name": "unknown_tool", "arguments": {}}),
            ProviderReply(tool_call=[{"name": TOOL_NAME, "arguments": self.booking_arguments()}]),
            ProviderReply(tool_call={"name": TOOL_NAME}),
            ProviderReply(text="   "),
        )
        expected_codes = ("unsupported_tool", "provider_error", "provider_error", "provider_error")
        for reply, code in zip(replies, expected_codes):
            with self.subTest(code=code):
                self.fake = FakeProvider(reply)

                result = self.run_fake(self.fake)

                self.assertFalse(result.success)
                self.assertEqual(result.code, code)
                self.assertEqual(Appointment.objects.count(), 0)
                self.assertEqual(AgentActionLog.objects.count(), 0)

    def test_tool_round_limit_never_dispatches_the_fourth_request(self):
        self.assertEqual(MAX_TOOL_ROUNDS, 3)
        alternate_vehicle = self.make_vehicle(self.owner, "INT-SECOND")
        self.fake = FakeProvider(
            ProviderReply(
                tool_call={"name": "check_required_maintenance", "arguments": {"vehicle_id": self.vehicle.pk}}
            ),
            ProviderReply(
                tool_call={"name": "list_available_service_slots", "arguments": {"service_type_id": self.service.pk}}
            ),
            ProviderReply(
                tool_call={"name": TOOL_NAME, "arguments": self.booking_arguments()}
            ),
            ProviderReply(
                tool_call={
                    "name": "check_required_maintenance",
                    "arguments": {"vehicle_id": alternate_vehicle.pk},
                }
            ),
        )

        result = self.run_fake(self.fake)

        # The booking result remains true even though the fourth Provider Tool
        # request is stopped; the committed Appointment must never be reported
        # as failed and accidentally encouraged to retry.
        self.assertTrue(result.success)
        self.assertIn("interaction limit", result.data["assistant_message"])
        self.assertEqual(AgentActionLog.objects.count(), MAX_TOOL_ROUNDS)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(len(self.fake.calls), MAX_TOOL_ROUNDS + 1)
