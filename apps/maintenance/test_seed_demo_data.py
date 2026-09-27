import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    ServiceSlot,
)
from apps.inventory.models import SparePart
from apps.vehicles.models import Vehicle

from .models import MaintenancePart, MaintenanceRecord, ServiceType, TechnicianProfile
from .services import get_vehicle_maintenance_overview


User = get_user_model()
DEMO_APPOINTMENT_PREFIX = "CARVIX_DEMO_SEED:v1:appointment:"
DEMO_RECORD_PREFIX = "CARVIX_DEMO_SEED:v1:record:"
DEMO_SERVICE_PREFIX = "CARVIX_DEMO_SEED:v1:service:"
DEMO_USERNAMES = (
    "demo.owner.one",
    "demo.owner.two",
    "demo.technician.one",
    "demo.technician.two",
    "demo.administrator",
)


class DemoSeedCommandTests(TestCase):
    def run_seed(self):
        output = StringIO()
        with patch.dict(os.environ, {"CARVIX_DEMO_PASSWORD": ""}):
            call_command("seed_demo_data", stdout=output)
        return output.getvalue()

    def snapshot(self):
        return (
            User.objects.filter(username__in=DEMO_USERNAMES).count(),
            TechnicianProfile.objects.filter(user__username__in=DEMO_USERNAMES).count(),
            Vehicle.objects.filter(license_plate__startswith="DEMO-VEH-").count(),
            ServiceType.objects.filter(description__startswith=DEMO_SERVICE_PREFIX).count(),
            Appointment.objects.filter(notes__startswith=DEMO_APPOINTMENT_PREFIX).count(),
            ServiceSlot.objects.filter(
                appointments__notes__startswith=DEMO_APPOINTMENT_PREFIX
            ).distinct().count(),
            MaintenanceRecord.objects.filter(notes__startswith=DEMO_RECORD_PREFIX).count(),
            SparePart.objects.filter(part_number__startswith="DEMO-PART-").count(),
            MaintenancePart.objects.filter(
                maintenance_record__notes__startswith=DEMO_RECORD_PREFIX
            ).count(),
        )

    def test_command_creates_constraint_valid_multi_owner_demo_dataset(self):
        output = self.run_seed()

        self.assertIn("users=5 (owners=2, technicians=2, administrators=1)", output)
        self.assertEqual(self.snapshot(), (5, 2, 3, 4, 6, 6, 3, 3, 2))

        users = {user.username: user for user in User.objects.filter(username__in=DEMO_USERNAMES)}
        self.assertEqual(
            User.objects.filter(username__in=DEMO_USERNAMES, role=User.Role.OWNER).count(), 2
        )
        self.assertEqual(
            User.objects.filter(username__in=DEMO_USERNAMES, role=User.Role.TECHNICIAN).count(), 2
        )
        self.assertEqual(
            User.objects.filter(
                username__in=DEMO_USERNAMES, role=User.Role.ADMINISTRATOR
            ).count(), 1
        )
        self.assertEqual(
            set(
                TechnicianProfile.objects.filter(user__username__in=DEMO_USERNAMES)
                .values_list("user__username", flat=True)
            ),
            {"demo.technician.one", "demo.technician.two"},
        )
        self.assertEqual(users["demo.owner.one"].vehicles.count(), 2)
        self.assertEqual(users["demo.owner.two"].vehicles.count(), 1)
        self.assertFalse(
            TechnicianProfile.objects.filter(
                user__in=(users["demo.owner.one"], users["demo.owner.two"], users["demo.administrator"])
            ).exists()
        )
        self.assertTrue(all(user.check_password("anything") is False for user in users.values()))

        for model in (Vehicle, ServiceType, ServiceSlot, Appointment, MaintenanceRecord, SparePart, MaintenancePart):
            queryset = model.objects.all()
            if model is Vehicle:
                queryset = queryset.filter(license_plate__startswith="DEMO-VEH-")
            elif model is ServiceType:
                queryset = queryset.filter(description__startswith=DEMO_SERVICE_PREFIX)
            elif model is ServiceSlot:
                queryset = queryset.filter(appointments__notes__startswith=DEMO_APPOINTMENT_PREFIX).distinct()
            elif model is Appointment:
                queryset = queryset.filter(notes__startswith=DEMO_APPOINTMENT_PREFIX)
            elif model is MaintenanceRecord:
                queryset = queryset.filter(notes__startswith=DEMO_RECORD_PREFIX)
            elif model is SparePart:
                queryset = queryset.filter(part_number__startswith="DEMO-PART-")
            elif model is MaintenancePart:
                queryset = queryset.filter(maintenance_record__notes__startswith=DEMO_RECORD_PREFIX)
            for instance in queryset:
                with self.subTest(model=model.__name__, pk=instance.pk):
                    instance.full_clean()

        future_slots = ServiceSlot.objects.filter(
            appointments__notes__startswith=f"{DEMO_APPOINTMENT_PREFIX}future:",
            is_active=True,
            start_time__gt=timezone.now(),
        ).distinct()
        self.assertEqual(future_slots.count(), 3)
        self.assertEqual(
            ServiceSlot.objects.filter(
                appointments__notes__startswith=f"{DEMO_APPOINTMENT_PREFIX}history:",
                is_active=False,
            ).distinct().count(),
            3,
        )
        full_slot = ServiceSlot.objects.get(
            appointments__notes=f"{DEMO_APPOINTMENT_PREFIX}future:owner_one_full"
        )
        self.assertEqual(
            full_slot.appointments.filter(status__in=ACTIVE_APPOINTMENT_STATUSES).count(),
            full_slot.capacity,
        )
        self.assertEqual(
            Appointment.objects.filter(
                notes__startswith=f"{DEMO_APPOINTMENT_PREFIX}future:",
                status=AppointmentStatus.PENDING,
                booked_by_agent=False,
            ).count(),
            3,
        )

        # Seeded usage is historical data only; it does not mutate stock quantities.
        self.assertEqual(
            list(
                SparePart.objects.filter(part_number__startswith="DEMO-PART-")
                .order_by("part_number")
                .values_list("quantity", flat=True)
            ),
            [35, 18, 0],
        )

    def test_repeated_command_run_is_idempotent(self):
        self.run_seed()
        before = self.snapshot()

        self.run_seed()

        self.assertEqual(self.snapshot(), before)

    def test_seeded_history_exercises_existing_due_service_calculation(self):
        self.run_seed()
        vehicle = Vehicle.objects.get(license_plate="DEMO-VEH-001")

        overview = get_vehicle_maintenance_overview(vehicle, as_of=timezone.localdate())

        statuses = {result.service_type.name: result.status for result in overview["due_services"]}
        self.assertEqual(statuses["Demo Oil and Filter Service"], "DUE")
        self.assertEqual(statuses["Demo Brake Fluid Service"], "NOT_DUE")
        self.assertEqual(statuses["Demo Tire Service"], "OVERDUE")
        self.assertEqual(statuses["Demo Air Filter Service"], "NO_HISTORY")

    def test_optional_local_password_environment_variable_is_used_without_output(self):
        demo_password = "test-only-not-a-real-credential"
        output = StringIO()
        with patch.dict(os.environ, {"CARVIX_DEMO_PASSWORD": demo_password}):
            call_command("seed_demo_data", stdout=output)

        owner = User.objects.get(username="demo.owner.one")
        self.assertTrue(owner.check_password(demo_password))
        self.assertNotIn(demo_password, output.getvalue())
