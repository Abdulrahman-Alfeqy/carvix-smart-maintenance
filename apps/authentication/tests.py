from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth.hashers import identify_hasher
from apps.authentication.models import User as AuthUser
from unittest import skipIf

User = get_user_model()

# Check if we are using PostgreSQL (to conditionally block DB constraint tests if not, but the prompt says to write them anyway)
is_postgres = settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'

class UserModelTests(TestCase):
    def test_regular_user_creation(self):
        user = User.objects.create_user(username="testuser", email="test@example.com", password="password123")
        self.assertTrue(user.is_active)
        self.assertIsNotNone(user.date_joined)
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.email, "test@example.com")

    def test_default_owner_role(self):
        user = User.objects.create_user(username="owneruser", email="owner@example.com", password="password123")
        self.assertEqual(user.role, User.Role.OWNER)

    def test_explicit_technician_role(self):
        user = User.objects.create_user(username="techuser", email="tech@example.com", password="password123", role=User.Role.TECHNICIAN)
        user.full_clean()
        self.assertEqual(user.role, User.Role.TECHNICIAN)

    def test_explicit_administrator_role(self):
        user = User.objects.create_user(username="adminuser", email="admin@example.com", password="password123", role=User.Role.ADMINISTRATOR)
        user.full_clean()
        self.assertEqual(user.role, User.Role.ADMINISTRATOR)

    def test_invalid_role_rejection_model_validation(self):
        user = User(username="invaliduser", email="invalid@example.com", password="password123", role="MANAGER")
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_required_email_validation(self):
        user = User(username="noemail", email="", password="password123")
        with self.assertRaises(ValidationError):
            user.full_clean()

    def test_unique_email_validation(self):
        User.objects.create_user(username="user1", email="duplicate@example.com", password="password123")
        user2 = User(username="user2", email="duplicate@example.com", password="password123")
        with self.assertRaises(ValidationError):
            user2.full_clean()

    def test_password_stored_differently(self):
        raw_password = "password123"
        user = User.objects.create_user(username="passuser", email="pass@example.com", password=raw_password)
        self.assertNotEqual(user.password, raw_password)
        self.assertNotEqual(user.password, "")

    def test_check_password_correct(self):
        user = User.objects.create_user(username="checkpass1", email="check1@example.com", password="correct_password")
        self.assertTrue(user.check_password("correct_password"))

    def test_check_password_wrong(self):
        user = User.objects.create_user(username="checkpass2", email="check2@example.com", password="correct_password")
        self.assertFalse(user.check_password("wrong_password"))

    def test_optional_encoded_password_verification(self):
        user = User.objects.create_user(username="hasheruser", email="hasher@example.com", password="password123")
        try:
            hasher = identify_hasher(user.password)
            self.assertIsNotNone(hasher)
        except ValueError:
            self.fail("identify_hasher raised ValueError unexpectedly!")

    def test_superuser_creation(self):
        admin_user = User.objects.create_superuser(username="super", email="super@example.com", password="password123")
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)

    def test_separation_between_role_and_flags(self):
        user = User.objects.create_user(username="separated", email="separated@example.com", password="password123", role=User.Role.ADMINISTRATOR)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

        super_user = User.objects.create_superuser(username="super_sep", email="super_sep@example.com", password="password123")
        # Ensure that superuser creation doesn't force ADMINISTRATOR role
        self.assertEqual(super_user.role, User.Role.OWNER)

    def test_correct_auth_user_model_configuration(self):
        self.assertEqual(settings.AUTH_USER_MODEL, "authentication.User")

    def test_correct_result_from_get_user_model(self):
        self.assertIs(get_user_model(), AuthUser)

    def test_correct_authentication_application_label(self):
        self.assertEqual(AuthUser._meta.app_label, 'authentication')

    def test_django_system_checks(self):
        try:
            call_command("check")
        except Exception as e:
            self.fail(f"System checks failed: {e}")

class UserDatabaseConstraintTests(TransactionTestCase):
    @skipIf(not is_postgres, "Database constraint tests require PostgreSQL")
    def test_invalid_role_rejection_database_constraint(self):
        with self.assertRaises(IntegrityError):
            User.objects.create(username="dbinvalid", email="dbinvalid@example.com", password="password123", role="MANAGER")
