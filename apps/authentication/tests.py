from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.conf import settings
from django.core.management import call_command
from django.contrib.auth.hashers import identify_hasher
from django.urls import reverse
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


class RegistrationTests(TestCase):
    def test_registration_page_loads(self):
        response = self.client.get(reverse("authentication:register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "authentication/register.html")

    def test_valid_registration_succeeds(self):
        response = self.client.post(reverse("authentication:register"), {
            "username": "newuser",
            "email": "newuser@example.com",
            "first_name": "New",
            "last_name": "User",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        self.assertRedirects(response, reverse("authentication:profile"))
        self.assertTrue(User.objects.filter(username="newuser").exists())

    def test_successful_registration_creates_authenticated_session(self):
        self.client.post(reverse("authentication:register"), {
            "username": "newuser2",
            "email": "newuser2@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        response = self.client.get(reverse("authentication:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user"].username, "newuser2")

    def test_created_password_is_hashed_not_raw(self):
        self.client.post(reverse("authentication:register"), {
            "username": "hashuser",
            "email": "hashuser@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        user = User.objects.get(username="hashuser")
        self.assertNotEqual(user.password, "ComplexPass123!")

    def test_check_password_succeeds_for_correct_password(self):
        self.client.post(reverse("authentication:register"), {
            "username": "checkuser",
            "email": "checkuser@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        user = User.objects.get(username="checkuser")
        self.assertTrue(user.check_password("ComplexPass123!"))

    def test_new_user_receives_owner_role(self):
        self.client.post(reverse("authentication:register"), {
            "username": "roleuser",
            "email": "roleuser@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        user = User.objects.get(username="roleuser")
        self.assertEqual(user.role, User.Role.OWNER)

    def test_new_user_is_not_staff(self):
        self.client.post(reverse("authentication:register"), {
            "username": "staffuser",
            "email": "staffuser@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        user = User.objects.get(username="staffuser")
        self.assertFalse(user.is_staff)

    def test_new_user_is_not_superuser(self):
        self.client.post(reverse("authentication:register"), {
            "username": "superuser2",
            "email": "superuser2@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        user = User.objects.get(username="superuser2")
        self.assertFalse(user.is_superuser)

    def test_duplicate_username_rejected(self):
        User.objects.create_user(username="existing", email="existing@example.com", password="password123")
        response = self.client.post(reverse("authentication:register"), {
            "username": "existing",
            "email": "different@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "username", "A user with that username already exists.")

    def test_duplicate_email_rejected(self):
        User.objects.create_user(username="user1", email="duplicate@example.com", password="password123")
        response = self.client.post(reverse("authentication:register"), {
            "username": "user2",
            "email": "duplicate@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "email", "A user with that email already exists.")

    def test_password_mismatch_rejected(self):
        response = self.client.post(reverse("authentication:register"), {
            "username": "mismatchuser",
            "email": "mismatch@example.com",
            "password1": "ComplexPass123!",
            "password2": "DifferentPass456!",
        })
        self.assertEqual(response.status_code, 200)
        password_errors = response.context["form"].errors.as_data()["password2"]
        self.assertEqual(password_errors[0].code, "password_mismatch")
    def test_weak_password_rejected(self):
        response = self.client.post(reverse("authentication:register"), {
            "username": "weakuser",
            "email": "weak@example.com",
            "password1": "123",
            "password2": "123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(form_has_errors(response, "password2"))

    def test_role_absent_from_registration_form(self):
        response = self.client.get(reverse("authentication:register"))
        self.assertNotIn("role", response.context["form"].fields)

    def test_is_staff_absent_from_registration_form(self):
        response = self.client.get(reverse("authentication:register"))
        self.assertNotIn("is_staff", response.context["form"].fields)

    def test_is_superuser_absent_from_registration_form(self):
        response = self.client.get(reverse("authentication:register"))
        self.assertNotIn("is_superuser", response.context["form"].fields)

    def test_submitted_role_cannot_escalate_account(self):
        self.client.post(reverse("authentication:register"), {
            "username": "escalateuser",
            "email": "escalate@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
            "role": "ADMINISTRATOR",
        })
        user = User.objects.get(username="escalateuser")
        self.assertEqual(user.role, User.Role.OWNER)

    def test_submitted_is_staff_cannot_escalate_account(self):
        self.client.post(reverse("authentication:register"), {
            "username": "escalateuser2",
            "email": "escalate2@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
            "is_staff": "True",
        })
        user = User.objects.get(username="escalateuser2")
        self.assertFalse(user.is_staff)

    def test_submitted_is_superuser_cannot_escalate_account(self):
        self.client.post(reverse("authentication:register"), {
            "username": "escalateuser3",
            "email": "escalate3@example.com",
            "password1": "ComplexPass123!",
            "password2": "ComplexPass123!",
            "is_superuser": "True",
        })
        user = User.objects.get(username="escalateuser3")
        self.assertFalse(user.is_superuser)

    def test_authenticated_user_redirected_from_registration(self):
        user = User.objects.create_user(username="authuser", email="auth@example.com", password="password123")
        self.client.force_login(user)
        response = self.client.get(reverse("authentication:register"))
        self.assertRedirects(response, reverse("authentication:profile"))


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="loginuser", email="login@example.com", password="ComplexPass123!")

    def test_login_page_loads(self):
        response = self.client.get(reverse("authentication:login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "authentication/login.html")

    def test_valid_login_succeeds(self):
        response = self.client.post(reverse("authentication:login"), {
            "username": "loginuser",
            "password": "ComplexPass123!",
        })
        self.assertRedirects(response, reverse("authentication:profile"))

    def test_invalid_login_fails(self):
        response = self.client.post(reverse("authentication:login"), {
            "username": "loginuser",
            "password": "WrongPass123!",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], None, "Please enter a correct username and password. Note that both fields may be case-sensitive.")

    def test_valid_login_creates_authenticated_session(self):
        self.client.post(reverse("authentication:login"), {
            "username": "loginuser",
            "password": "ComplexPass123!",
        })
        response = self.client.get(reverse("authentication:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["user"].username, "loginuser")

    def test_authenticated_user_redirected_from_login(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("authentication:login"))
        self.assertRedirects(response, reverse("authentication:profile"))

    def test_safe_internal_next_redirect_works(self):
        response = self.client.post(reverse("authentication:login") + "?next=/accounts/profile/", {
            "username": "loginuser",
            "password": "ComplexPass123!",
        })
        self.assertRedirects(response, "/accounts/profile/")

    def test_unsafe_external_next_redirect_rejected(self):
        response = self.client.post(reverse("authentication:login") + "?next=https://evil.example/", {
            "username": "loginuser",
            "password": "ComplexPass123!",
        })
        self.assertRedirects(response, reverse("authentication:profile"))

    def test_post_logout_ends_authenticated_session(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("authentication:logout"))
        self.assertRedirects(response, reverse("authentication:login"))
        response = self.client.get(reverse("authentication:profile"))
        self.assertRedirects(response, reverse("authentication:login") + "?next=" + reverse("authentication:profile"))

    def test_get_logout_returns_method_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("authentication:logout"))
        self.assertEqual(response.status_code, 405)

    def test_logout_redirects_to_login(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("authentication:logout"))
        self.assertRedirects(response, reverse("authentication:login"))


class ProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="profileuser", email="profile@example.com", password="ComplexPass123!")
        self.other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="ComplexPass123!")

    def test_anonymous_profile_access_redirects_to_login(self):
        response = self.client.get(reverse("authentication:profile"))
        self.assertRedirects(response, reverse("authentication:login") + "?next=" + reverse("authentication:profile"))

    def test_anonymous_profile_edit_access_redirects_to_login(self):
        response = self.client.get(reverse("authentication:profile_edit"))
        self.assertRedirects(response, reverse("authentication:login") + "?next=" + reverse("authentication:profile_edit"))

    def test_authenticated_user_can_view_own_profile(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("authentication:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "profileuser")
        self.assertContains(response, "profile@example.com")

    def test_profile_url_does_not_require_user_id(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("authentication:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("user_id", response.request["PATH_INFO"])

    def test_authenticated_user_can_edit_approved_fields(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("authentication:profile_edit"), {
            "email": "updated@example.com",
            "first_name": "Updated",
            "last_name": "User",
        })
        self.assertRedirects(response, reverse("authentication:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated@example.com")
        self.assertEqual(self.user.first_name, "Updated")
        self.assertEqual(self.user.last_name, "User")

    def test_profile_update_redirects_to_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("authentication:profile_edit"), {
            "email": "updated2@example.com",
            "first_name": "Updated",
            "last_name": "User",
        })
        self.assertRedirects(response, reverse("authentication:profile"))

    def test_duplicate_email_update_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("authentication:profile_edit"), {
            "email": "other@example.com",
            "first_name": "Updated",
            "last_name": "User",
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "email", "A user with that email already exists.")

    def test_submitted_role_cannot_modify_stored_role(self):
        self.client.force_login(self.user)
        self.client.post(reverse("authentication:profile_edit"), {
            "email": "profile@example.com",
            "first_name": "Updated",
            "last_name": "User",
            "role": "ADMINISTRATOR",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, User.Role.OWNER)

    def test_submitted_is_staff_cannot_modify_is_staff(self):
        self.client.force_login(self.user)
        self.client.post(reverse("authentication:profile_edit"), {
            "email": "profile@example.com",
            "first_name": "Updated",
            "last_name": "User",
            "is_staff": "True",
        })
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_staff)

    def test_submitted_is_superuser_cannot_modify_is_superuser(self):
        self.client.force_login(self.user)
        self.client.post(reverse("authentication:profile_edit"), {
            "email": "profile@example.com",
            "first_name": "Updated",
            "last_name": "User",
            "is_superuser": "True",
        })
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_superuser)

    def test_submitted_username_cannot_modify_username(self):
        self.client.force_login(self.user)
        self.client.post(reverse("authentication:profile_edit"), {
            "email": "profile@example.com",
            "first_name": "Updated",
            "last_name": "User",
            "username": "newusername",
        })
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "profileuser")

    def test_privileged_fields_absent_from_profile_edit_form(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("authentication:profile_edit"))
        form = response.context["form"]
        self.assertNotIn("role", form.fields)
        self.assertNotIn("is_staff", form.fields)
        self.assertNotIn("is_superuser", form.fields)
        self.assertNotIn("username", form.fields)
        self.assertNotIn("groups", form.fields)
        self.assertNotIn("user_permissions", form.fields)


def form_has_errors(response, field_name):
    form = response.context.get("form")
    if form and field_name in form.errors:
        return True
    return False
