import os
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentStatus, ServiceSlot
from apps.appointments.services import AppointmentBookingError, book_appointment
from apps.authentication.models import User
from apps.inventory.models import SparePart
from apps.vehicles.models import Vehicle

from ...models import MaintenancePart, MaintenanceRecord, ServiceType, TechnicianProfile
from ...services import add_calendar_months


DEMO_PREFIX = "CARVIX_DEMO_SEED:v1:"
APPOINTMENT_PREFIX = f"{DEMO_PREFIX}appointment:"
SERVICE_DESCRIPTION_PREFIX = f"{DEMO_PREFIX}service:"


class Command(BaseCommand):
    help = "Create or refresh deterministic local CARVIX demonstration data."

    def handle(self, *args, **options):
        password = os.environ.get("CARVIX_DEMO_PASSWORD") or None
        with transaction.atomic():
            users = self._users(password)
            technicians = self._technicians(users)
            vehicles = self._vehicles(users)
            services = self._services()
            parts = self._parts()
            records = self._historical_records(technicians, vehicles, services)
            self._maintenance_parts(records, parts)
            self._future_bookings(users, vehicles, services)
            self._assert_role_profile_integrity(users)

        self.stdout.write(self.style.SUCCESS(self._summary(password_provided=bool(password))))

    def _users(self, password):
        definitions = (
            ("owner_one", "demo.owner.one", "demo.owner.one@carvix.test", User.Role.OWNER, "Amina", "Owner"),
            ("owner_two", "demo.owner.two", "demo.owner.two@carvix.test", User.Role.OWNER, "Omar", "Owner"),
            ("tech_one", "demo.technician.one", "demo.technician.one@carvix.test", User.Role.TECHNICIAN, "Nadia", "Technician"),
            ("tech_two", "demo.technician.two", "demo.technician.two@carvix.test", User.Role.TECHNICIAN, "Karim", "Technician"),
            ("administrator", "demo.administrator", "demo.administrator@carvix.test", User.Role.ADMINISTRATOR, "Salma", "Administrator"),
        )
        users = {}
        for key, username, email, role, first_name, last_name in definitions:
            user = User.objects.filter(username=username).first()
            if user is None:
                user = User(
                    username=username,
                    email=email,
                    role=role,
                    first_name=first_name,
                    last_name=last_name,
                    is_active=True,
                )
                user.set_password(password)
            else:
                if user.email.casefold() != email.casefold():
                    raise CommandError(
                        f"Reserved demo username collision for {username}; no data was changed."
                    )
                user.email = email
                user.role = role
                user.first_name = first_name
                user.last_name = last_name
                user.is_active = True
                if password:
                    user.set_password(password)
            user.full_clean()
            user.save()
            users[key] = user
        return users

    def _technicians(self, users):
        definitions = (
            (users["tech_one"], "General maintenance"),
            (users["tech_two"], "Brakes and tires"),
        )
        profiles = {}
        for index, (user, specialization) in enumerate(definitions, start=1):
            profile, _ = TechnicianProfile.objects.get_or_create(
                user=user,
                defaults={"specialization": specialization, "is_available": True},
            )
            profile.specialization = specialization
            profile.is_available = True
            profile.full_clean()
            profile.save()
            profiles[f"tech_{index}"] = profile
        return profiles

    def _vehicles(self, users):
        definitions = (
            ("owner_one", "DEMO-VEH-001", "Toyota", "Camry", 2022, 45000),
            ("owner_one", "DEMO-VEH-002", "Honda", "Civic", 2021, 12000),
            ("owner_two", "DEMO-VEH-003", "Hyundai", "Tucson", 2023, 38000),
        )
        vehicles = {}
        for owner_key, plate, manufacturer, model, year, mileage in definitions:
            vehicle = Vehicle.objects.filter(license_plate=plate).first()
            if vehicle is None:
                vehicle = Vehicle(
                    owner=users[owner_key],
                    manufacturer=manufacturer,
                    model=model,
                    model_year=year,
                    license_plate=plate,
                    current_mileage=mileage,
                )
            elif vehicle.owner_id != users[owner_key].pk:
                raise CommandError(
                    f"Reserved demo vehicle collision for {plate}; no data was changed."
                )
            else:
                if (vehicle.manufacturer, vehicle.model, vehicle.model_year) != (
                    manufacturer,
                    model,
                    year,
                ):
                    raise CommandError(
                        f"Reserved demo vehicle identity changed for {plate}; no data was changed."
                    )
                vehicle.manufacturer = manufacturer
                vehicle.model = model
                vehicle.model_year = year
                vehicle.current_mileage = mileage
            vehicle.full_clean()
            vehicle.save()
            vehicles[plate] = vehicle
        return vehicles

    def _services(self):
        definitions = (
            ("Demo Oil and Filter Service", "Oil and filter replacement.", 5000, 6, 45, "35.00"),
            ("Demo Brake Fluid Service", "Brake fluid inspection and replacement.", 40000, 24, 60, "75.00"),
            ("Demo Tire Service", "Tire inspection and rotation.", 20000, 12, 40, "45.00"),
            ("Demo Air Filter Service", "Engine air filter inspection and replacement.", 15000, 12, 30, "25.00"),
        )
        services = {}
        for key, (name, description, interval_km, interval_months, duration, price) in zip(
            ("oil", "brakes", "tires", "air_filter"), definitions
        ):
            marker = f"{SERVICE_DESCRIPTION_PREFIX}{key}"
            service = ServiceType.objects.filter(name=name).first()
            if service is not None and not service.description.startswith(DEMO_PREFIX):
                raise CommandError(
                    f"Reserved demo service-name collision for {name}; no data was changed."
                )
            if service is None:
                service = ServiceType(name=name)
            service.description = f"{marker} {description}"
            service.interval_km = interval_km
            service.interval_months = interval_months
            service.duration_minutes = duration
            service.price = Decimal(price)
            service.full_clean()
            service.save()
            services[key] = service
        return services

    def _parts(self):
        definitions = (
            ("DEMO-PART-001", "Demo Oil Filter", 35, 5, "8.50"),
            ("DEMO-PART-002", "Demo Brake Fluid", 18, 4, "12.00"),
            ("DEMO-PART-003", "Demo Air Filter", 0, 3, "16.25"),
        )
        parts = {}
        for part_number, name, quantity, minimum_stock, price in definitions:
            part = SparePart.objects.filter(part_number=part_number).first()
            if part is not None and not part.name.startswith("Demo "):
                raise CommandError(
                    f"Reserved demo part-number collision for {part_number}; no data was changed."
                )
            if part is None:
                part = SparePart(part_number=part_number)
            part.name = name
            part.quantity = quantity
            part.minimum_stock = minimum_stock
            part.unit_price = Decimal(price)
            part.full_clean()
            part.save()
            parts[part_number] = part
        return parts

    def _slot_for(self, appointment_tag, start, capacity, is_active):
        end = start + timedelta(minutes=60)
        appointment = (
            Appointment.objects.filter(notes=appointment_tag)
            .select_related("slot")
            .first()
        )
        if appointment is not None:
            slot = appointment.slot
            other_appointments = slot.appointments.exclude(
                notes__startswith=APPOINTMENT_PREFIX
            )
            if other_appointments.exists() and (
                slot.start_time != start
                or slot.end_time != end
                or slot.capacity != capacity
                or slot.is_active != is_active
            ):
                raise CommandError(
                    "A seed slot has non-seed appointments and cannot be refreshed safely."
                )
            slot.start_time = start
            slot.end_time = end
            slot.capacity = capacity
            slot.is_active = is_active
            slot.full_clean()
            slot.save()
            return slot

        collision = ServiceSlot.objects.filter(
            start_time=start,
            end_time=end,
            capacity=capacity,
            is_active=is_active,
        ).first()
        if collision is not None:
            raise CommandError(
                "A ServiceSlot matches a reserved demo time; refusing to reuse an unmarked slot."
            )
        slot = ServiceSlot(
            start_time=start,
            end_time=end,
            capacity=capacity,
            is_active=is_active,
        )
        slot.full_clean()
        slot.save()
        return slot

    def _future_bookings(self, users, vehicles, services):
        today = timezone.localdate()
        definitions = (
            ("owner_one_full", users["owner_one"], vehicles["DEMO-VEH-001"], 1, 1),
            ("owner_two_open", users["owner_two"], vehicles["DEMO-VEH-003"], 2, 3),
            ("owner_one_open", users["owner_one"], vehicles["DEMO-VEH-002"], 3, 5),
        )
        for key, owner, vehicle, capacity, day_offset in definitions:
            tag = f"{APPOINTMENT_PREFIX}future:{key}"
            start = timezone.make_aware(
                datetime.combine(today + timedelta(days=day_offset), time(hour=10))
            )
            slot = self._slot_for(tag, start, capacity, True)
            appointment = Appointment.objects.filter(notes=tag).first()
            if appointment is None:
                try:
                    appointment = book_appointment(
                        actor=owner,
                        vehicle_id=vehicle.pk,
                        service_type_id=services["oil"].pk,
                        slot_id=slot.pk,
                    )
                except AppointmentBookingError as error:
                    raise CommandError(
                        f"Could not create deterministic demo booking ({error.code}): {error}"
                    ) from error
                appointment.notes = tag
                appointment.save(update_fields=("notes",))

    def _historical_records(self, technicians, vehicles, services):
        today = timezone.localdate()
        vehicle = vehicles["DEMO-VEH-001"]
        definitions = (
            ("oil_due", services["oil"], technicians["tech_1"], 40000,
             add_calendar_months(today, -5), "Oil service is exactly due by mileage."),
            ("brakes_not_due", services["brakes"], technicians["tech_2"], 10000,
             add_calendar_months(today, -1), "Brake-fluid service remains within both intervals."),
            ("tires_overdue", services["tires"], technicians["tech_1"], 10000,
             add_calendar_months(today, -13), "Tire service is overdue by mileage and date."),
        )
        records = {}
        for key, service, technician, mileage, service_date, note in definitions:
            appointment_tag = f"{APPOINTMENT_PREFIX}history:{key}"
            legacy_record_marker = f"{DEMO_PREFIX}record:{key}"
            slot_start = timezone.make_aware(
                datetime.combine(service_date, time(hour=9))
            )
            slot = self._slot_for(appointment_tag, slot_start, 1, False)
            appointment, _ = Appointment.objects.get_or_create(
                notes=appointment_tag,
                defaults={
                    "vehicle": vehicle,
                    "service_type": service,
                    "slot": slot,
                    "technician": technician,
                    "status": AppointmentStatus.COMPLETED,
                    "booked_by_agent": False,
                },
            )
            if (
                appointment.vehicle_id != vehicle.pk
                or appointment.service_type_id != service.pk
                or appointment.slot_id != slot.pk
                or appointment.technician_id != technician.pk
                or appointment.status != AppointmentStatus.COMPLETED
            ):
                raise CommandError(
                    f"Seed historical appointment {key} no longer matches its reserved identity."
                )

            record = MaintenanceRecord.objects.filter(appointment=appointment).first()
            if record is None:
                # Upgrade records created by the previous marker-in-notes seed format.
                record = MaintenanceRecord.objects.filter(notes=legacy_record_marker).first()
            is_new_record = record is None
            if record is None:
                record = MaintenanceRecord()
            else:
                expected_record_identity = (
                    record.vehicle_id == vehicle.pk
                    and record.service_type_id == service.pk
                    and record.technician_id == technician.pk
                    and record.appointment_id == appointment.pk
                    and record.service_date == service_date
                    and record.mileage_at_service == mileage
                )
                if not expected_record_identity:
                    raise CommandError(
                        f"Seed historical record {key} no longer matches its reserved identity."
                    )
            record.vehicle = vehicle
            record.service_type = service
            record.technician = technician
            record.appointment = appointment
            record.service_date = service_date
            record.mileage_at_service = mileage
            if is_new_record or not record.notes or record.notes == legacy_record_marker:
                record.notes = note
            record.full_clean()
            record.save()
            records[key] = record
        return records

    def _maintenance_parts(self, records, parts):
        definitions = (
            (records["oil_due"], parts["DEMO-PART-001"], 1),
            (records["brakes_not_due"], parts["DEMO-PART-002"], 1),
        )
        for record, part, quantity_used in definitions:
            item, _ = MaintenancePart.objects.update_or_create(
                maintenance_record=record,
                spare_part=part,
                defaults={"quantity_used": quantity_used},
            )
            item.full_clean()

    def _assert_role_profile_integrity(self, users):
        invalid_profiles = TechnicianProfile.objects.exclude(
            user__role=User.Role.TECHNICIAN
        ).filter(user__in=users.values())
        if invalid_profiles.exists():
            raise CommandError("A seeded TechnicianProfile is linked to a non-Technician user.")
        if TechnicianProfile.objects.filter(
            user__in=(users["owner_one"], users["owner_two"], users["administrator"])
        ).exists():
            raise CommandError("A seeded Owner or Administrator has a TechnicianProfile.")

    def _summary(self, *, password_provided):
        credential_status = (
            "Seeded demo credentials are usable because CARVIX_DEMO_PASSWORD was provided."
            if password_provided
            else "Seeded account passwords are unusable because CARVIX_DEMO_PASSWORD was not provided."
        )
        return (
            "Demo data ready: users=5 (owners=2, technicians=2, administrators=1); "
            "technician_profiles=2; vehicles=3; service_types=4; service_slots=6; "
            "appointments=6 (pending=3, historical_completed=3); "
            f"maintenance_records=3; spare_parts=3; maintenance_parts=2. {credential_status}"
        )
