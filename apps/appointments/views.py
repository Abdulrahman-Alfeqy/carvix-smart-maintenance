from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import DetailView, FormView, ListView

from apps.authentication.models import User
from apps.maintenance.models import TechnicianProfile
from apps.vehicles.models import Vehicle
from apps.vehicles.views import OwnerRequiredMixin

from .forms import (
    AppointmentBookingForm,
    MaintenanceCompletionForm,
    SparePartUsageFormSet,
    TechnicianAssignmentForm,
)
from .models import Appointment, AppointmentStatus
from .services import (
    AppointmentBookingError,
    TechnicianAssignmentError,
    TechnicianMaintenanceError,
    assign_technician,
    book_appointment,
    complete_appointment_maintenance,
    start_appointment_service,
)


class AdministratorRequiredMixin(UserPassesTestMixin):
    """Restrict assignment endpoints to the CARVIX Administrator role."""

    def test_func(self):
        return self.request.user.role == User.Role.ADMINISTRATOR


class AdministratorAppointmentAssignmentListView(
    LoginRequiredMixin, AdministratorRequiredMixin, ListView
):
    template_name = "appointments/administrator_assignment_list.html"
    context_object_name = "appointments"
    login_url = reverse_lazy("authentication:login")

    def get_queryset(self):
        return (
            Appointment.objects.filter(technician__isnull=True)
            .select_related("vehicle", "service_type", "slot")
        )


class AdministratorAppointmentAssignmentView(
    LoginRequiredMixin, AdministratorRequiredMixin, FormView
):
    form_class = TechnicianAssignmentForm
    template_name = "appointments/administrator_assignment_form.html"
    login_url = reverse_lazy("authentication:login")

    def get_appointment(self):
        return get_object_or_404(
            Appointment.objects.filter(technician__isnull=True).select_related(
                "vehicle", "service_type", "slot"
            ),
            pk=self.kwargs["appointment_pk"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["appointment"] = self.get_appointment()
        return context

    def form_valid(self, form):
        try:
            appointment = assign_technician(
                actor=self.request.user,
                appointment_id=self.kwargs["appointment_pk"],
                technician_profile_id=form.cleaned_data["technician"].pk,
            )
        except TechnicianAssignmentError as error:
            if error.code in {"appointment_not_found", "already_assigned"}:
                raise Http404 from error
            form.add_error(None, str(error))
            return self.form_invalid(form)

        messages.success(
            self.request,
            f"Technician assigned to Appointment {appointment.pk}.",
        )
        return redirect("appointments:administrator-assignment-list")


class TechnicianRequiredMixin(UserPassesTestMixin):
    """Require the Technician role and its corresponding profile."""

    def test_func(self):
        if self.request.user.role != User.Role.TECHNICIAN:
            return False
        try:
            self.technician_profile = self.request.user.technician_profile
        except TechnicianProfile.DoesNotExist:
            return False
        return True


class TechnicianAppointmentQuerysetMixin:
    """Limit Appointment reads to the authenticated Technician's assignment."""

    def get_queryset(self):
        return (
            Appointment.objects.filter(technician=self.technician_profile)
            .select_related("vehicle", "service_type", "slot")
        )


class TechnicianAppointmentListView(
    LoginRequiredMixin, TechnicianRequiredMixin, TechnicianAppointmentQuerysetMixin, ListView
):
    template_name = "appointments/technician_appointment_list.html"
    context_object_name = "appointments"
    login_url = reverse_lazy("authentication:login")


class TechnicianAppointmentDetailView(
    LoginRequiredMixin,
    TechnicianRequiredMixin,
    TechnicianAppointmentQuerysetMixin,
    DetailView,
):
    template_name = "appointments/technician_appointment_detail.html"
    context_object_name = "appointment"
    login_url = reverse_lazy("authentication:login")


class TechnicianStartServiceView(
    LoginRequiredMixin, TechnicianRequiredMixin, TechnicianAppointmentQuerysetMixin, View
):
    login_url = reverse_lazy("authentication:login")

    def post(self, request, *args, **kwargs):
        appointment = self.get_queryset().filter(pk=kwargs["pk"]).first()
        if appointment is None:
            raise Http404
        try:
            start_appointment_service(actor=request.user, appointment_id=appointment.pk)
        except TechnicianMaintenanceError as error:
            if error.code == "appointment_not_found":
                raise Http404 from error
            messages.error(request, str(error))
        else:
            messages.success(request, f"Appointment {appointment.pk} started.")
        return redirect("appointments:technician-appointment-detail", pk=appointment.pk)


class TechnicianMaintenanceCompletionView(
    LoginRequiredMixin,
    TechnicianRequiredMixin,
    TechnicianAppointmentQuerysetMixin,
    FormView,
):
    form_class = MaintenanceCompletionForm
    template_name = "appointments/technician_maintenance_completion.html"
    login_url = reverse_lazy("authentication:login")

    def get_appointment(self):
        if not hasattr(self, "_appointment"):
            self._appointment = get_object_or_404(
                self.get_queryset(), pk=self.kwargs["pk"]
            )
        return self._appointment

    def get_formset(self):
        if not hasattr(self, "_formset"):
            data = self.request.POST if self.request.method == "POST" else None
            self._formset = SparePartUsageFormSet(data=data, prefix="parts")
        return self._formset

    def get(self, request, *args, **kwargs):
        if self.get_appointment().status != AppointmentStatus.IN_PROGRESS:
            raise Http404
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["appointment"] = self.get_appointment()
        context["parts_formset"] = kwargs.get("parts_formset", self.get_formset())
        return context

    def form_valid(self, form):
        formset = self.get_formset()
        if not formset.is_valid():
            form.add_error(None, "Correct the SparePart entries or remove incomplete rows.")
            return self.form_invalid(form)
        usages = []
        for part_form in formset:
            values = part_form.cleaned_data
            part = values.get("spare_part")
            quantity = values.get("quantity_used")
            if part is None and quantity is None:
                continue
            if part is None or quantity is None:
                part_form.add_error(None, "Choose a part and enter its quantity.")
                form.add_error(None, "Correct the incomplete SparePart entries.")
                return self.form_invalid(form)
            usages.append((part.pk, quantity))

        appointment = self.get_appointment()
        try:
            record = complete_appointment_maintenance(
                actor=self.request.user,
                appointment_id=appointment.pk,
                mileage_at_service=form.cleaned_data["mileage_at_service"],
                notes=form.cleaned_data["notes"],
                parts=usages,
            )
        except TechnicianMaintenanceError as error:
            if error.code == "appointment_not_found":
                raise Http404 from error
            form.add_error(None, str(error))
            return self.form_invalid(form)

        messages.success(self.request, "Maintenance was completed and recorded.")
        return redirect(
            "appointments:technician-appointment-detail",
            pk=record.appointment_id,
        )


class OwnerAppointmentQuerysetMixin:
    """Keep appointment reads within the authenticated Owner's vehicles."""

    def get_queryset(self):
        return (
            Appointment.objects.filter(vehicle__owner=self.request.user)
            .select_related("vehicle", "service_type", "slot")
        )


class OwnerAppointmentListView(
    LoginRequiredMixin, OwnerRequiredMixin, OwnerAppointmentQuerysetMixin, ListView
):
    template_name = "appointments/appointment_list.html"
    context_object_name = "appointments"
    login_url = reverse_lazy("authentication:login")


class OwnerAppointmentDetailView(
    LoginRequiredMixin, OwnerRequiredMixin, OwnerAppointmentQuerysetMixin, DetailView
):
    template_name = "appointments/appointment_detail.html"
    context_object_name = "appointment"
    login_url = reverse_lazy("authentication:login")

    def get_queryset(self):
        return super().get_queryset().select_related("technician__user")


class AppointmentBookingView(LoginRequiredMixin, OwnerRequiredMixin, FormView):
    form_class = AppointmentBookingForm
    template_name = "appointments/booking_form.html"
    login_url = reverse_lazy("authentication:login")

    def get_vehicle(self):
        return get_object_or_404(
            Vehicle.objects.filter(owner=self.request.user),
            pk=self.kwargs["vehicle_pk"],
        )

    def get_initial(self):
        initial = super().get_initial()
        initial["vehicle"] = self.get_vehicle().pk
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["owner"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["vehicle"] = self.get_vehicle()
        context["has_available_slots"] = context["form"].has_available_slots
        return context

    def form_valid(self, form):
        try:
            appointment = book_appointment(
                actor=self.request.user,
                vehicle_id=form.cleaned_data["vehicle"].pk,
                service_type_id=form.cleaned_data["service_type"].pk,
                slot_id=form.cleaned_data["slot"].pk,
            )
        except AppointmentBookingError as error:
            form.add_error(None, str(error))
            return self.form_invalid(form)

        messages.success(
            self.request,
            (
                f"Appointment {appointment.pk} booked for {appointment.vehicle.license_plate}: "
                f"{appointment.service_type.name} at {appointment.slot.start_time}."
            ),
        )
        return redirect("vehicles:vehicle-detail", pk=appointment.vehicle_id)
