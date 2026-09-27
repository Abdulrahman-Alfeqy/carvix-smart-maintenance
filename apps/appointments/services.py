from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.authentication.models import User
from apps.maintenance.models import ServiceType, TechnicianProfile
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
