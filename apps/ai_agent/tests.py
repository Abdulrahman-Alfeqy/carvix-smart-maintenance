import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, skipUnlessDBFeature
from django.utils import timezone

from .admin import AgentActionLogAdmin
from .models import AgentActionLog
from .sanitization import REDACTED, sanitize_payload

User = get_user_model()


class AgentActionLogModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="owner",
            email="owner@example.test",
            password="safe-test-password",
        )

    def create_log(self, **overrides):
        data = {
            "user": self.user,
            "tool_name": "check_required_maintenance",
            "arguments": {"vehicle_id": 42},
            "result": {"success": True, "data": {"items": []}},
            "status": AgentActionLog.Status.SUCCESS,
            "duration_ms": 0,
        }
        data.update(overrides)
        return AgentActionLog.objects.create(**data)

    def test_saves_json_payload_timestamp_and_status(self):
        before = timezone.now()
        log = self.create_log()
        log.refresh_from_db()
        self.assertEqual(log.arguments, {"vehicle_id": 42})
        self.assertTrue(log.result["success"])
        self.assertGreaterEqual(log.created_at, before)
        self.assertEqual(log.duration_ms, 0)

    def test_failure_status_must_match_result(self):
        with self.assertRaises(ValidationError):
            self.create_log(status=AgentActionLog.Status.FAILURE)

    def test_result_requires_boolean_success(self):
        with self.assertRaises(ValidationError):
            self.create_log(result={"success": "yes"})

    def test_negative_duration_rejected(self):
        with self.assertRaises(ValidationError):
            self.create_log(duration_ms=-1)

    def test_user_deletion_is_protected(self):
        self.create_log()
        with self.assertRaises(ProtectedError):
            self.user.delete()

    def test_newest_first_order_has_stable_primary_key_tiebreaker(self):
        first = self.create_log()
        second = self.create_log()
        same_time = timezone.now() - timedelta(minutes=1)
        AgentActionLog.objects.filter(pk__in=(first.pk, second.pk)).update(created_at=same_time)
        self.assertEqual(
            list(AgentActionLog.objects.values_list("pk", flat=True)),
            [second.pk, first.pk],
        )

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_database_rejects_invalid_status(self):
        log = AgentActionLog(
            user=self.user,
            tool_name="tool",
            arguments={},
            result={"success": True},
            status="INVALID",
            duration_ms=0,
        )
        with self.assertRaises(ValidationError):
            log.full_clean()
        log.status = "INVALID"
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentActionLog.objects.bulk_create([log])


class AgentActionLogSanitizationTests(TestCase):
    def test_sensitive_keys_are_recursively_redacted_without_mutating_input(self):
        source = {
            "Password": "p",
            "db_password": "p2",
            "API-Key": "key",
            "nested": [{"Authorization": "bearer", "safe": 3}],
            "dsn": "postgres://secret",
        }
        original = json.loads(json.dumps(source))
        cleaned = sanitize_payload(source)
        self.assertEqual(source, original)
        self.assertEqual(cleaned["Password"], REDACTED)
        self.assertEqual(cleaned["db_password"], REDACTED)
        self.assertEqual(cleaned["API-Key"], REDACTED)
        self.assertEqual(cleaned["nested"][0]["Authorization"], REDACTED)
        self.assertEqual(cleaned["nested"][0]["safe"], 3)
        self.assertEqual(cleaned["dsn"], REDACTED)
        self.assertEqual(json.loads(json.dumps(cleaned)), cleaned)
        self.assertEqual(sanitize_payload(source), cleaned)

    def test_unsupported_values_and_non_string_keys_are_rejected(self):
        with self.assertRaises(ValidationError):
            sanitize_payload({"value": object()})
        with self.assertRaises(ValidationError):
            sanitize_payload({1: "value"})

    def test_top_level_payload_must_be_object(self):
        with self.assertRaises(ValidationError):
            sanitize_payload(["not", "an", "object"])


class AgentActionLogAdminTests(TestCase):
    def setUp(self):
        self.permission = Permission.objects.get(
            content_type__app_label="ai_agent",
            codename="view_agentactionlog",
        )

    def create_admin_user(self, username, role):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="safe-test-password",
            role=role,
            is_staff=True,
        )
        user.user_permissions.add(self.permission)
        return user

    def test_domain_administrator_with_view_permission_can_inspect(self):
        user = self.create_admin_user("domain-admin", User.Role.ADMINISTRATOR)
        client = Client()
        client.force_login(user)
        response = client.get("/admin/ai_agent/agentactionlog/")
        self.assertEqual(response.status_code, 200)

    def test_non_administrator_staff_is_denied(self):
        user = self.create_admin_user("staff-owner", User.Role.OWNER)
        client = Client()
        client.force_login(user)
        response = client.get("/admin/ai_agent/agentactionlog/")
        self.assertEqual(response.status_code, 403)

    def test_domain_role_does_not_grant_staff_or_superuser(self):
        user = User.objects.create_user(
            username="plain-admin-role",
            email="plain-admin@example.test",
            password="safe-test-password",
            role=User.Role.ADMINISTRATOR,
        )
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_admin_is_read_only(self):
        from django.contrib import admin

        model_admin = AgentActionLogAdmin(AgentActionLog, admin.site)
        request = type("Request", (), {"user": User(role=User.Role.ADMINISTRATOR)})()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))
        self.assertFalse(model_admin.has_delete_permission(request))
        self.assertEqual(len(model_admin.get_readonly_fields(request)), len(AgentActionLog._meta.fields))

    @skipUnlessDBFeature("supports_table_check_constraints")
    def test_database_rejects_negative_duration(self):
        user = self.create_admin_user("duration-admin", User.Role.ADMINISTRATOR)
        log = AgentActionLog(
            user=user,
            tool_name="tool",
            arguments={},
            result={"success": True},
            status=AgentActionLog.Status.SUCCESS,
            duration_ms=-1,
        )
        with self.assertRaises(ValidationError):
            log.full_clean()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AgentActionLog.objects.bulk_create([log])
