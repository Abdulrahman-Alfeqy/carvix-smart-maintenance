"""Focused Plan 016 booking-tool, dispatcher, audit, and Chat coverage."""

import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_agent.agent import respond_to_message
from apps.ai_agent.booking_tool import TOOL_NAME, book_maintenance_appointment
from apps.ai_agent.maintenance_tool import check_required_maintenance
from apps.ai_agent.models import AgentActionLog
from apps.ai_agent.provider import ProviderReply
from apps.ai_agent.slot_tool import list_available_service_slots
from apps.ai_agent.tools import TOOL_REGISTRY, _register_tool, execute_tool_request
from apps.appointments.models import Appointment, AppointmentStatus, ServiceSlot
from apps.maintenance.models import ServiceType
from apps.vehicles.models import Vehicle


User = get_user_model()
RESULT_KEYS = {"success", "code", "message", "data", "errors"}
_DEFAULT_ACTOR = object()


class BookingToolFixtures(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="tool-owner",
            email="tool-owner@example.test",
            password="test-password",
        )
        self.other_owner = User.objects.create_user(
            username="tool-other-owner",
            email="tool-other@example.test",
            password="test-password",
        )
        self.technician = User.objects.create_user(
            username="tool-technician",
            email="tool-tech@example.test",
            password="test-password",
            role=User.Role.TECHNICIAN,
        )
        self.administrator = User.objects.create_user(
            username="tool-administrator",
            email="tool-admin@example.test",
            password="test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.service = ServiceType.objects.create(
            name="AI tool service",
            description="Test service",
            interval_km=1000,
            interval_months=12,
            duration_minutes=30,
            price=Decimal("10.00"),
        )
        self.slot = self.make_slot()
        self.vehicle = self.make_vehicle(self.owner, "TOOL-OWN")
        self.foreign_vehicle = self.make_vehicle(self.other_owner, "TOOL-OTHER")

    def make_slot(self, **overrides):
        start_time = timezone.now() + timedelta(days=1)
        fields = {
            "start_time": start_time,
            "end_time": start_time + timedelta(minutes=30),
            "capacity": 2,
        }
        fields.update(overrides)
        return ServiceSlot.objects.create(**fields)

    def make_vehicle(self, owner, plate):
        return Vehicle.objects.create(
            owner=owner,
            manufacturer="Toyota",
            model="Yaris",
            model_year=2022,
            license_plate=plate,
            current_mileage=100,
        )

    def arguments(self, **overrides):
        values = {
            "vehicle_id": self.vehicle.pk,
            "service_type_id": self.service.pk,
            "slot_id": self.slot.pk,
            "confirmation": True,
        }
        values.update(overrides)
        return values

    def execute(self, arguments=None, *, actor=_DEFAULT_ACTOR, handler=None, name=TOOL_NAME):
        registry = {name: handler} if handler is not None else None
        return execute_tool_request(
            name,
            self.arguments() if arguments is None else arguments,
            actor=self.owner if actor is _DEFAULT_ACTOR else actor,
            registry=registry,
        )


class BookingToolInputTests(BookingToolFixtures):
    def test_public_registry_contains_exactly_the_three_approved_tools(self):
        self.assertEqual(
            tuple(TOOL_REGISTRY),
            (
                "check_required_maintenance",
                "list_available_service_slots",
                TOOL_NAME,
            ),
        )
        self.assertIs(TOOL_REGISTRY[TOOL_NAME], book_maintenance_appointment)
        self.assertIs(TOOL_REGISTRY["check_required_maintenance"], check_required_maintenance)
        self.assertIs(TOOL_REGISTRY["list_available_service_slots"], list_available_service_slots)

    def test_registry_rejects_duplicate_names_and_noncallable_handlers(self):
        registry = {"already_registered": lambda **kwargs: {}}

        self.assertFalse(_register_tool(registry, "already_registered", lambda **kwargs: {}))
        self.assertFalse(_register_tool(registry, "not_callable", object()))
        self.assertEqual(tuple(registry), ("already_registered",))

    def test_confirmed_booking_accepts_integer_and_decimal_free_string_ids(self):
        values = self.arguments(
            vehicle_id=str(self.vehicle.pk),
            service_type_id=str(self.service.pk),
            slot_id=str(self.slot.pk),
        )
        result = self.execute(values)

        self.assertEqual(set(result), RESULT_KEYS)
        self.assertTrue(result["success"])
        self.assertEqual(result["code"], "ok")
        self.assertEqual(Appointment.objects.count(), 1)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.vehicle, self.vehicle)
        self.assertEqual(appointment.service_type, self.service)
        self.assertEqual(appointment.slot, self.slot)
        self.assertEqual(appointment.status, AppointmentStatus.PENDING)
        self.assertTrue(appointment.booked_by_agent)
        self.assertEqual(
            set(result["data"]),
            {
                "appointment_id",
                "vehicle_id",
                "service_type_id",
                "slot_id",
                "status",
            },
        )
        self.assertEqual(AgentActionLog.objects.count(), 1)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.status, AgentActionLog.Status.SUCCESS)
        self.assertEqual(log.user, self.owner)
        self.assertEqual(log.tool_name, TOOL_NAME)
        self.assertEqual(log.arguments, values)
        self.assertEqual(log.result, result)
        self.assertGreaterEqual(log.duration_ms, 0)

    def test_ai_flag_is_passed_to_creation_without_a_follow_up_update(self):
        original_save = Appointment.save
        save_calls = []

        def capture_save(instance, *args, **kwargs):
            save_calls.append(
                (instance.pk, kwargs.get("force_insert"), kwargs.get("update_fields"))
            )
            return original_save(instance, *args, **kwargs)

        with patch.object(Appointment, "save", capture_save):
            result = self.execute()

        self.assertTrue(result["success"])
        appointment = Appointment.objects.get()
        self.assertTrue(appointment.booked_by_agent)
        self.assertEqual(len(save_calls), 1)
        self.assertIsNone(save_calls[0][0])
        self.assertIsNone(save_calls[0][2])

    def test_missing_false_and_non_boolean_confirmation_never_book(self):
        samples = (
            ({key: value for key, value in self.arguments().items() if key != "confirmation"}, "confirmation_required"),
            (self.arguments(confirmation=False), "confirmation_required"),
            (self.arguments(confirmation="true"), "validation_error"),
            (self.arguments(confirmation=1), "validation_error"),
        )
        for args, expected_code in samples:
            with self.subTest(expected_code=expected_code, args=args):
                result = self.execute(args)
                self.assertFalse(result["success"])
                self.assertEqual(result["code"], expected_code)
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), len(samples))
        self.assertTrue(
            AgentActionLog.objects.filter(status=AgentActionLog.Status.FAILURE).exists()
        )

    def test_missing_ids_extra_fields_and_identity_fields_are_rejected(self):
        bad_arguments = (
            {},
            {key: value for key, value in self.arguments().items() if key != "vehicle_id"},
            {key: value for key, value in self.arguments().items() if key != "service_type_id"},
            {key: value for key, value in self.arguments().items() if key != "slot_id"},
            {**self.arguments(), "user_id": self.other_owner.pk},
            {**self.arguments(), "owner_id": self.other_owner.pk},
            {**self.arguments(), "role": User.Role.ADMINISTRATOR},
            {**self.arguments(), "is_staff": True},
            {**self.arguments(), "is_superuser": True},
            {**self.arguments(), "booked_by_agent": True},
            {**self.arguments(), "status": AppointmentStatus.CONFIRMED},
            {**self.arguments(), "capacity": 999},
            {**self.arguments(), "notes": "not accepted"},
        )
        for args in bad_arguments:
            with self.subTest(args=args):
                self.assertEqual(self.execute(args)["code"], "validation_error")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), len(bad_arguments))
        logs = list(AgentActionLog.objects.order_by("id"))
        empty_args_log = logs[0]
        self.assertEqual(empty_args_log.arguments, {"_supplied_arguments": {}})
        self.assertEqual(
            empty_args_log.result,
            {
                "success": False,
                "code": "validation_error",
                "message": "The booking details are invalid. Check the selected vehicle, service, and slot.",
                "data": None,
                "errors": {
                    "service_type_id": "This field is required.",
                    "slot_id": "This field is required.",
                    "vehicle_id": "This field is required.",
                },
            },
        )
        self.assertEqual(empty_args_log.status, AgentActionLog.Status.FAILURE)
        self.assertGreaterEqual(empty_args_log.duration_ms, 0)
        self.assertTrue(all(log.status == AgentActionLog.Status.FAILURE for log in logs))

    def test_boolean_zero_negative_fractional_and_malformed_ids_are_rejected(self):
        invalid_ids = (True, False, 0, -1, 1.5, "1.5", "x", "١")
        for invalid in invalid_ids:
            with self.subTest(identifier=invalid):
                result = self.execute(self.arguments(vehicle_id=invalid))
                self.assertEqual(result["code"], "validation_error")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), len(invalid_ids))

    def test_non_object_arguments_are_audited_as_safe_validation_failure(self):
        result = self.execute(["unexpected", "values"])

        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["code"], "validation_error")
        self.assertEqual(Appointment.objects.count(), 0)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.arguments, {"invalid_arguments": True})
        self.assertEqual(log.status, AgentActionLog.Status.FAILURE)


class BookingToolAuthorizationTests(BookingToolFixtures):
    def test_only_an_authenticated_owner_can_use_the_tool(self):
        for actor in (None, object(), self.technician, self.administrator):
            with self.subTest(actor=actor):
                result = self.execute(actor=actor)
                self.assertEqual(result["code"], "permission_denied")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 2)

    def test_staff_or_superuser_flags_do_not_grant_owner_role(self):
        self.technician.is_staff = True
        self.technician.is_superuser = True
        self.technician.save(update_fields=("is_staff", "is_superuser"))

        result = self.execute(actor=self.technician)

        self.assertEqual(result["code"], "permission_denied")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)

    def test_foreign_or_missing_vehicle_returns_safe_denial(self):
        foreign = self.execute(self.arguments(vehicle_id=self.foreign_vehicle.pk))
        missing = self.execute(self.arguments(vehicle_id=2_000_000_000))

        self.assertEqual(foreign["code"], "permission_denied")
        self.assertEqual(missing["code"], "permission_denied")
        self.assertNotIn("TOOL-OTHER", json.dumps(foreign))
        self.assertNotIn("tool-other-owner", json.dumps(foreign))
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 2)


class BookingToolOutcomeTests(BookingToolFixtures):
    def test_domain_failures_are_mapped_without_raw_exception_messages(self):
        invalid_service = self.execute(self.arguments(service_type_id=2_000_000_000))
        expired_slot = self.make_slot(
            start_time=timezone.now() - timedelta(days=1),
            end_time=timezone.now() - timedelta(days=1) + timedelta(minutes=30),
        )
        expired = self.execute(self.arguments(slot_id=expired_slot.pk))
        full_slot = self.make_slot(capacity=1)
        other = self.make_vehicle(self.owner, "TOOL-FULL")
        Appointment.objects.create(vehicle=other, service_type=self.service, slot=full_slot)
        full = self.execute(self.arguments(slot_id=full_slot.pk))

        self.assertEqual(invalid_service["code"], "not_found")
        self.assertEqual(expired["code"], "slot_unavailable")
        self.assertEqual(full["code"], "slot_unavailable")
        self.assertFalse(invalid_service["success"])
        self.assertEqual(AgentActionLog.objects.count(), 3)
        self.assertEqual(
            AgentActionLog.objects.filter(status=AgentActionLog.Status.FAILURE).count(),
            3,
        )

    def test_active_duplicate_is_reported_and_does_not_add_an_appointment(self):
        Appointment.objects.create(vehicle=self.vehicle, service_type=self.service, slot=self.slot)

        result = self.execute()

        self.assertEqual(result["code"], "duplicate_booking")
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_failed_booking_service_result_creates_no_appointment(self):
        from apps.appointments.services import AppointmentBookingError

        with patch(
            "apps.ai_agent.booking_tool.book_appointment",
            side_effect=AppointmentBookingError("private details", "slot_full"),
        ):
            result = self.execute()

        self.assertEqual(result["code"], "slot_unavailable")
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)


class ToolDispatcherAuditTests(BookingToolFixtures):
    def test_unexpected_handler_exception_is_contained_and_audited_once(self):
        def broken_handler(*, actor, arguments):
            Appointment.objects.create(
                vehicle=self.vehicle,
                service_type=self.service,
                slot=self.slot,
            )
            raise RuntimeError("synthetic secret and database details")

        result = self.execute(
            self.arguments(), handler=broken_handler, name="test_registered_tool"
        )

        self.assertEqual(set(result), RESULT_KEYS)
        self.assertEqual(result["code"], "internal_error")
        self.assertNotIn("synthetic", json.dumps(result))
        self.assertNotIn("database", json.dumps(result))
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.status, AgentActionLog.Status.FAILURE)
        self.assertNotIn("synthetic", json.dumps(log.result))
        self.assertGreaterEqual(log.duration_ms, 0)
        self.assertIsNotNone(log.created_at)

    def test_malformed_and_nonserializable_results_become_one_safe_failure(self):
        invalid_results = (
            lambda **kwargs: "not an object",
            lambda **kwargs: {"success": True},
            lambda **kwargs: {
                "success": True,
                "code": "ok",
                "message": "done",
                "data": object(),
                "errors": None,
            },
            lambda **kwargs: {
                "success": "yes",
                "code": "ok",
                "message": "done",
                "data": None,
                "errors": None,
            },
        )
        for handler in invalid_results:
            with self.subTest(handler=handler):
                result = self.execute(
                    self.arguments(), handler=handler, name="test_registered_tool"
                )
                self.assertEqual(result["code"], "invalid_tool_result")
        self.assertEqual(AgentActionLog.objects.count(), len(invalid_results))
        self.assertEqual(
            AgentActionLog.objects.filter(status=AgentActionLog.Status.FAILURE).count(),
            len(invalid_results),
        )

    def test_malformed_result_rolls_back_handler_side_effect_before_failure_audit(self):
        def side_effect_then_malformed(*, actor, arguments):
            Appointment.objects.create(
                vehicle=self.vehicle,
                service_type=self.service,
                slot=self.slot,
            )
            return {"success": True, "code": "ok"}

        result = self.execute(
            self.arguments(),
            handler=side_effect_then_malformed,
            name="test_registered_tool",
        )

        self.assertEqual(result["code"], "invalid_tool_result")
        self.assertFalse(result["success"])
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_success_and_failure_result_status_must_match_audit(self):
        self.execute()
        self.execute(self.arguments(confirmation=False))

        self.assertEqual(
            list(AgentActionLog.objects.order_by("id").values_list("status", flat=True)),
            [AgentActionLog.Status.SUCCESS, AgentActionLog.Status.FAILURE],
        )

    def test_nested_sensitive_arguments_are_sanitized(self):
        arguments = self.arguments()
        arguments["test_metadata"] = {"nested": [{"api_key": "hidden"}]}

        self.execute(arguments)

        self.assertEqual(
            AgentActionLog.objects.get().arguments["test_metadata"]["nested"][0]["api_key"],
            "[REDACTED]",
        )

    def test_unknown_tool_is_not_logged(self):
        result = self.execute(
            self.arguments(), name="apps.appointments.services.book_appointment"
        )

        self.assertEqual(result["code"], "unsupported_tool")
        self.assertEqual(AgentActionLog.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_noncallable_registered_entry_fails_safely_and_is_audited(self):
        result = execute_tool_request(
            "broken_registered_tool",
            self.arguments(),
            actor=self.owner,
            registry={"broken_registered_tool": object()},
        )

        self.assertEqual(result["code"], "unsupported_tool")
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)

    def test_success_audit_failure_rolls_back_booking_and_allows_clean_retry(self):
        audit_observed_appointment_counts = []

        def fail_success_audit(**kwargs):
            audit_observed_appointment_counts.append(Appointment.objects.count())
            raise OperationalError("private database details")

        with patch.object(
            AgentActionLog.objects,
            "create",
            side_effect=fail_success_audit,
        ) as create_audit:
            result = self.execute()

        self.assertEqual(create_audit.call_count, 1)
        self.assertEqual(audit_observed_appointment_counts, [1])
        self.assertFalse(result["success"])
        self.assertEqual(result["code"], "internal_error")
        self.assertEqual(
            result["message"],
            "The requested action could not be completed. Please try again later.",
        )
        self.assertNotIn("private database details", json.dumps(result))
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 0)
        self.assertEqual(
            Appointment.objects.filter(
                slot=self.slot,
                status__in=(
                    AppointmentStatus.PENDING,
                    AppointmentStatus.CONFIRMED,
                    AppointmentStatus.IN_PROGRESS,
                ),
            ).count(),
            0,
        )

        retry_result = self.execute()

        self.assertTrue(retry_result["success"])
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        appointment = Appointment.objects.get()
        self.assertTrue(appointment.booked_by_agent)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.SUCCESS)

    def test_failure_audit_store_failure_is_not_retried(self):
        with patch.object(
            AgentActionLog.objects,
            "create",
            side_effect=OperationalError("private database details"),
        ) as create_audit:
            result = self.execute({})

        self.assertEqual(create_audit.call_count, 1)
        self.assertEqual(result["code"], "internal_error")
        self.assertFalse(result["success"])
        self.assertNotIn("private database details", json.dumps(result))
        self.assertEqual(AgentActionLog.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_dispatcher_injects_the_actor_as_a_server_owned_argument(self):
        received = []

        def handler(*, actor, arguments):
            received.append((actor, arguments))
            return {
                "success": False,
                "code": "validation_error",
                "message": "Invalid input.",
                "data": None,
                "errors": {"field": "Invalid."},
            }

        self.execute(self.arguments(), actor=self.owner, handler=handler, name="test_tool")

        self.assertEqual(received, [(self.owner, self.arguments())])
        self.assertEqual(AgentActionLog.objects.get().user, self.owner)


class BookingToolChatIntegrationTests(BookingToolFixtures):
    class FakeProvider:
        def __init__(self, arguments):
            self.arguments = arguments

        def generate(self, *, message, system_prompt, context):
            return ProviderReply(
                tool_call={
                    "name": TOOL_NAME,
                    "arguments": self.arguments,
                }
            )

    def test_fake_provider_tool_call_uses_authenticated_actor_and_backend_result(self):
        provider = self.FakeProvider(self.arguments())
        with patch("apps.ai_agent.agent.get_provider", return_value=provider):
            result = respond_to_message(user=self.owner, message="Book the confirmed slot")

        self.assertTrue(result.success)
        self.assertEqual(result.code, "ok")
        self.assertEqual(Appointment.objects.count(), 1)
        log = AgentActionLog.objects.get()
        self.assertEqual(log.user, self.owner)
        self.assertEqual(log.tool_name, TOOL_NAME)

    def test_chat_endpoint_contains_handler_exception_without_false_success(self):
        self.client.force_login(self.owner)
        provider = self.FakeProvider(self.arguments())
        with (
            patch("apps.ai_agent.agent.get_provider", return_value=provider),
            patch(
                "apps.ai_agent.booking_tool.book_appointment",
                side_effect=RuntimeError("exception text must remain private"),
            ),
        ):
            response = self.client.post(
                reverse("ai_agent:chat-message"),
                json.dumps({"message": "Book my confirmed appointment"}),
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(response.json()["code"], "internal_error")
        self.assertNotIn("exception text", response.content.decode())
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(AgentActionLog.objects.count(), 1)
        self.assertEqual(AgentActionLog.objects.get().status, AgentActionLog.Status.FAILURE)
