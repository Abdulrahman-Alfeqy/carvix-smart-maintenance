from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.authentication.models import User
from apps.inventory.models import SparePart
from apps.maintenance.models import (
    MaintenancePart,
    MaintenanceRecord,
    ServiceType,
    TechnicianProfile,
)
from apps.vehicles.models import Vehicle

from .models import ACTIVE_APPOINTMENT_STATUSES, Appointment, AppointmentStatus, ServiceSlot


ACTIVE_SLOT_VEHICLE_UNIQUE_CONSTRAINT = "appointments_active_slot_vehicle_uniq"


def _is_active_duplicate_constraint(error):
    """Identify only the database constraint for duplicate active bookings."""
    database_error = error.__cause__
    diagnostic = getattr(database_error, "diag", None)
    return (
        getattr(diagnostic, "constraint_name", None)
        == ACTIVE_SLOT_VEHICLE_UNIQUE_CONSTRAINT
    )


class AppointmentBookingError(Exception):
    """Safe, form-facing failure raised when a booking cannot be completed."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class TechnicianAssignmentError(Exception):
    """Safe failure raised when an initial Technician assignment is invalid."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class TechnicianMaintenanceError(Exception):
    """Safe, form-facing rejection for Technician service operations."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def _technician_appointment_id(value):
    if isinstance(value, bool) or not (
        isinstance(value, int)
        or isinstance(value, str) and value.isascii() and value.isdecimal()
    ):
        raise TechnicianMaintenanceError(
            "This Appointment is unavailable.", code="appointment_not_found"
        )
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise TechnicianMaintenanceError(
            "This Appointment is unavailable.", code="appointment_not_found"
        ) from error
    if value <= 0:
        raise TechnicianMaintenanceError(
            "This Appointment is unavailable.", code="appointment_not_found"
        )
    return value


def _assigned_appointment_for_update(*, actor, appointment_id):
    if not getattr(actor, "is_authenticated", False) or getattr(actor, "role", None) != User.Role.TECHNICIAN:
        raise TechnicianMaintenanceError(
            "Only the assigned Technician can update this Appointment.",
            code="permission_denied",
        )
    try:
        technician = actor.technician_profile
    except TechnicianProfile.DoesNotExist as error:
        raise TechnicianMaintenanceError(
            "A Technician profile is required.", code="permission_denied"
        ) from error
    appointment_id = _technician_appointment_id(appointment_id)
    appointment = (
        Appointment.objects.select_for_update()
        .filter(pk=appointment_id, technician=technician)
        .select_related("vehicle", "service_type", "technician")
        .first()
    )
    if appointment is None:
        raise TechnicianMaintenanceError(
            "This Appointment is unavailable.", code="appointment_not_found"
        )
    return appointment, technician


def start_appointment_service(*, actor, appointment_id):
    """Move an assigned Appointment from PENDING/CONFIRMED to IN_PROGRESS."""
    with transaction.atomic():
        appointment, _technician = _assigned_appointment_for_update(
            actor=actor, appointment_id=appointment_id
        )
        if appointment.status not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
            raise TechnicianMaintenanceError(
                "This Appointment cannot be started from its current status.",
                code="invalid_status",
            )
        appointment.status = AppointmentStatus.IN_PROGRESS
        appointment.save(update_fields=("status",))
        return appointment


def complete_appointment_maintenance(
    *, actor, appointment_id, mileage_at_service, notes="", parts=()
):
    """Atomically record completed work and reduce inventory for an assigned Appointment."""
    with transaction.atomic():
        appointment, technician = _assigned_appointment_for_update(
            actor=actor, appointment_id=appointment_id
        )
        if appointment.status != AppointmentStatus.IN_PROGRESS:
            raise TechnicianMaintenanceError(
                "Only an in-progress Appointment can be completed.",
                code="invalid_status",
            )
        if appointment.maintenance_records.exists():
            raise TechnicianMaintenanceError(
                "This Appointment already has a maintenance record.",
                code="already_completed",
            )

        try:
            mileage = int(mileage_at_service)
        except (TypeError, ValueError, OverflowError) as error:
            raise TechnicianMaintenanceError(
                "Enter a valid service mileage.", code="invalid_mileage"
            ) from error
        if isinstance(mileage_at_service, bool) or mileage < 0:
            raise TechnicianMaintenanceError(
                "Mileage cannot be negative.", code="invalid_mileage"
            )
        if mileage < appointment.vehicle.current_mileage:
            raise TechnicianMaintenanceError(
                "Service mileage cannot be lower than the vehicle's accepted mileage.",
                code="mileage_below_current",
            )
        if not isinstance(notes, str):
            raise TechnicianMaintenanceError(
                "Enter valid maintenance notes.", code="invalid_notes"
            )

        normalized_parts = []
        seen_ids = set()
        try:
            submitted_parts = list(parts)
        except TypeError as error:
            raise TechnicianMaintenanceError(
                "Enter valid SparePart usage.", code="invalid_parts"
            ) from error
        for entry in submitted_parts:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise TechnicianMaintenanceError(
                    "Enter valid SparePart usage.", code="invalid_parts"
                )
            part_id, quantity = entry
            if isinstance(part_id, bool) or not (
                isinstance(part_id, int)
                or isinstance(part_id, str) and part_id.isascii() and part_id.isdecimal()
            ):
                raise TechnicianMaintenanceError(
                    "Choose a valid SparePart.", code="invalid_part"
                )
            try:
                part_id = int(part_id)
            except (TypeError, ValueError, OverflowError) as error:
                raise TechnicianMaintenanceError(
                    "Choose a valid SparePart.", code="invalid_part"
                ) from error
            if part_id <= 0 or part_id in seen_ids:
                raise TechnicianMaintenanceError(
                    "Each SparePart may be listed only once.", code="duplicate_part"
                )
            seen_ids.add(part_id)
            if isinstance(quantity, bool) or not (
                isinstance(quantity, int)
                or isinstance(quantity, str) and quantity.isascii() and quantity.isdecimal()
            ):
                raise TechnicianMaintenanceError(
                    "Enter a positive whole-number quantity for each SparePart.",
                    code="invalid_quantity",
                )
            try:
                quantity = int(quantity)
            except (TypeError, ValueError, OverflowError) as error:
                raise TechnicianMaintenanceError(
                    "Enter a positive whole-number quantity for each SparePart.",
                    code="invalid_quantity",
                ) from error
            if quantity <= 0:
                raise TechnicianMaintenanceError(
                    "Enter a positive whole-number quantity for each SparePart.",
                    code="invalid_quantity",
                )
            normalized_parts.append((part_id, quantity))

        part_ids = [part_id for part_id, _quantity in normalized_parts]
        locked_parts = list(
            SparePart.objects.select_for_update().filter(pk__in=part_ids).order_by("pk")
        )
        parts_by_id = {part.pk: part for part in locked_parts}
        if len(parts_by_id) != len(part_ids):
            raise TechnicianMaintenanceError(
                "One or more selected SpareParts are unavailable.", code="part_not_found"
            )
        for part_id, quantity in normalized_parts:
            part = parts_by_id[part_id]
            if part.quantity < quantity:
                raise TechnicianMaintenanceError(
                    f"Insufficient stock for {part.name}.", code="insufficient_stock"
                )

        record = MaintenanceRecord(
            vehicle=appointment.vehicle,
            service_type=appointment.service_type,
            technician=technician,
            appointment=appointment,
            service_date=timezone.localdate(),
            mileage_at_service=mileage,
            notes=notes,
        )
        try:
            record.full_clean()
        except ValidationError as error:
            raise TechnicianMaintenanceError(
                "The maintenance details are invalid.", code="invalid_record"
            ) from error
        record.save()

        for part_id, quantity in normalized_parts:
            part = parts_by_id[part_id]
            MaintenancePart.objects.create(
                maintenance_record=record,
                spare_part=part,
                quantity_used=quantity,
            )
            part.quantity -= quantity
            part.save(update_fields=("quantity",))

        appointment.status = AppointmentStatus.COMPLETED
        appointment.save(update_fields=("status",))
        appointment.refresh_from_db(fields=("status",))
        if appointment.status != AppointmentStatus.COMPLETED:
            raise TechnicianMaintenanceError(
                "Maintenance completion could not be saved.", code="completion_failed"
            )
        return record


def _assignment_id(value, *, label):
    if isinstance(value, bool) or not (
        isinstance(value, int)
        or isinstance(value, str) and value.isascii() and value.isdecimal()
    ):
        raise TechnicianAssignmentError(
            f"The selected {label} is invalid.", code=f"invalid_{label}"
        )
    value = int(value)
    if value <= 0:
        raise TechnicianAssignmentError(
            f"The selected {label} is invalid.", code=f"invalid_{label}"
        )
    return value


def assign_technician(*, actor, appointment_id, technician_profile_id):
    """Assign one available Technician to an unassigned Appointment.

    Actor identity is supplied by the server from `request.user`; the only
    Appointment field written is `technician`. The row lock prevents concurrent
    submissions from replacing an initial assignment.
    """
    if (
        not getattr(actor, "is_authenticated", False)
        or getattr(actor, "role", None) != User.Role.ADMINISTRATOR
    ):
        raise TechnicianAssignmentError(
            "Only an Administrator can assign a Technician.",
            code="permission_denied",
        )

    appointment_id = _assignment_id(appointment_id, label="appointment")
    technician_profile_id = _assignment_id(
        technician_profile_id, label="technician"
    )

    with transaction.atomic():
        appointment = (
            Appointment.objects.select_for_update()
            .filter(pk=appointment_id)
            .first()
        )
        if appointment is None:
            raise TechnicianAssignmentError(
                "The selected Appointment is unavailable.",
                code="appointment_not_found",
            )
        if appointment.technician_id is not None:
            raise TechnicianAssignmentError(
                "This Appointment already has a Technician assigned.",
                code="already_assigned",
            )

        technician = (
            TechnicianProfile.objects.select_for_update()
            .filter(
                pk=technician_profile_id,
                user__role=User.Role.TECHNICIAN,
                is_available=True,
            )
            .first()
        )
        if technician is None:
            raise TechnicianAssignmentError(
                "Choose an available Technician account.",
                code="invalid_technician",
            )

        appointment.technician = technician
        appointment.save(update_fields=("technician",))
        return appointment


def _selection_id(value):
    if isinstance(value, bool) or not (
        isinstance(value, int)
        or isinstance(value, str) and value.isascii() and value.isdecimal()
    ):
        raise AppointmentBookingError(
            "The selected vehicle, service, or time slot is invalid.",
            code="invalid_selection",
        )
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise AppointmentBookingError(
            "The selected vehicle, service, or time slot is invalid.",
            code="invalid_selection",
        ) from error
    if value <= 0:
        raise AppointmentBookingError(
            "The selected vehicle, service, or time slot is invalid.",
            code="invalid_selection",
        )
    return value


def book_appointment(*, actor, vehicle_id, service_type_id, slot_id):
    """Create an Owner's manual appointment after transactional revalidation.

    `actor` must be the authenticated server-side user (normally request.user).
    No identity or protected appointment fields are accepted from the payload.
    """
    if not getattr(actor, "is_authenticated", False) or getattr(actor, "role", None) != User.Role.OWNER:
        raise AppointmentBookingError(
            "Only an authenticated vehicle owner can book an appointment.",
            code="permission_denied",
        )

    vehicle_id = _selection_id(vehicle_id)
    service_type_id = _selection_id(service_type_id)
    slot_id = _selection_id(slot_id)

    try:
        with transaction.atomic():
            vehicle = Vehicle.objects.filter(owner=actor, pk=vehicle_id).first()
            if vehicle is None:
                raise AppointmentBookingError(
                    "The selected vehicle is unavailable.",
                    code="permission_denied",
                )

            try:
                service_type = ServiceType.objects.get(pk=service_type_id)
            except ServiceType.DoesNotExist as error:
                raise AppointmentBookingError(
                    "The selected service is unavailable.",
                    code="invalid_service",
                ) from error

            try:
                slot = ServiceSlot.objects.select_for_update().get(pk=slot_id)
            except ServiceSlot.DoesNotExist as error:
                raise AppointmentBookingError(
                    "The selected time slot is no longer available. Choose another slot.",
                    code="slot_unavailable",
                ) from error

            if not slot.is_active:
                raise AppointmentBookingError(
                    "This time slot is no longer active. Choose another slot.",
                    code="slot_inactive",
                )
            if slot.start_time <= timezone.now():
                raise AppointmentBookingError(
                    "This time slot has already started. Choose a future slot.",
                    code="slot_expired",
                )

            active_appointments = Appointment.objects.filter(
                slot=slot,
                status__in=ACTIVE_APPOINTMENT_STATUSES,
            )
            if active_appointments.filter(vehicle=vehicle).exists():
                raise AppointmentBookingError(
                    "This vehicle already has an active appointment in this time slot.",
                    code="duplicate_booking",
                )
            if active_appointments.count() >= slot.capacity:
                raise AppointmentBookingError(
                    "This time slot is full. Choose another slot.",
                    code="slot_full",
                )

            return Appointment.objects.create(
                vehicle=vehicle,
                service_type=service_type,
                slot=slot,
                status=AppointmentStatus.PENDING,
                technician=None,
                booked_by_agent=False,
            )
    except IntegrityError as error:
        # The atomic block has rolled back before translating the known duplicate race.
        if not _is_active_duplicate_constraint(error):
            raise
        raise AppointmentBookingError(
            "The appointment could not be booked because the slot changed. Refresh and choose another slot.",
            code="booking_conflict",
        ) from error
