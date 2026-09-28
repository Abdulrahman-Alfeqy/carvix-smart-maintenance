from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.contrib.staticfiles import finders
from django.test import Client, TestCase
from django.urls import reverse


User = get_user_model()


class StaticAssetDiscoveryTests(TestCase):
    def test_project_static_directory_and_collection_root_are_configured(self):
        project_static = Path(settings.BASE_DIR) / "static"
        static_root = Path(settings.BASE_DIR) / "staticfiles"

        self.assertEqual([Path(directory) for directory in settings.STATICFILES_DIRS], [project_static])
        self.assertEqual(Path(settings.STATIC_ROOT), static_root)
        self.assertNotIn(static_root, [Path(directory) for directory in settings.STATICFILES_DIRS])

    def test_findstatic_resolves_project_assets_once(self):
        for asset in ("js/agent_chat.js", "css/carvix.css"):
            with self.subTest(asset=asset):
                output = StringIO()
                call_command("findstatic", asset, verbosity=2, stdout=output)
                expected_path = str(Path(settings.BASE_DIR) / "static" / asset)
                resolved_paths = finders.find(asset, find_all=True)

                self.assertIn("Found", output.getvalue())
                self.assertEqual(resolved_paths, [expected_path])
                self.assertIn(expected_path, output.getvalue())


class RootEntrySmokeTests(TestCase):
    def test_anonymous_root_redirects_to_login_and_ignores_external_next(self):
        response = self.client.get("/?next=https://example.invalid/", follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("authentication:login"))
        self.assertEqual(User.objects.count(), 0)

    def test_authenticated_root_follows_existing_login_to_profile_convention(self):
        owner = User.objects.create_user(
            username="root-owner",
            email="root-owner@example.test",
            password="safe-test-password",
            role=User.Role.OWNER,
        )
        self.client.force_login(owner)

        response = self.client.get("/", follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.redirect_chain,
            [
                (reverse("authentication:login"), 302),
                (reverse("authentication:profile"), 302),
            ],
        )
        self.assertContains(response, "Profile")
        self.assertEqual(User.objects.count(), 1)


class ChatBrowserContractTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="chat-nav-owner",
            email="chat-nav-owner@example.test",
            password="safe-test-password",
            role=User.Role.OWNER,
        )
        self.technician = User.objects.create_user(
            username="chat-nav-technician",
            email="chat-nav-technician@example.test",
            password="safe-test-password",
            role=User.Role.TECHNICIAN,
        )
        self.administrator = User.objects.create_user(
            username="chat-nav-administrator",
            email="chat-nav-administrator@example.test",
            password="safe-test-password",
            role=User.Role.ADMINISTRATOR,
        )

    def test_authenticated_navigation_adds_chat_without_removing_role_links(self):
        role_links = (
            (self.owner, "vehicles:vehicle-list", "appointments:appointment-list"),
            (self.technician, "appointments:technician-appointment-list", None),
            (self.administrator, "appointments:administrator-assignment-list", None),
        )
        chat_url = reverse("ai_agent:chat")

        for user, first_role_route, second_role_route in role_links:
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("authentication:profile"))

                self.assertContains(response, f'href="{chat_url}">Assistant</a>')
                self.assertContains(response, f'href="{reverse(first_role_route)}"')
                if second_role_route:
                    self.assertContains(response, f'href="{reverse(second_role_route)}"')

        self.client.logout()
        anonymous_response = self.client.get(reverse("authentication:login"))
        self.assertNotContains(anonymous_response, f'href="{chat_url}">Assistant</a>')

    def test_chat_page_renders_csrf_json_contract_and_script(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("ai_agent:chat"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/ai/chat/message/"')
        self.assertContains(response, 'data-endpoint="/ai/chat/message/"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, '<script src="/static/js/agent_chat.js" defer></script>')

        script = (Path(settings.BASE_DIR) / "static" / "js" / "agent_chat.js").read_text()
        for contract in (
            "fetch(form.dataset.endpoint",
            '"Content-Type": "application/json"',
            '"X-CSRFToken": csrfInput.value',
            'credentials: "same-origin"',
            "JSON.stringify({ message })",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, script)

    def test_anonymous_chat_page_remains_protected(self):
        response = self.client.get(reverse("ai_agent:chat"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"{reverse('authentication:login')}?next={reverse('ai_agent:chat')}",
        )
