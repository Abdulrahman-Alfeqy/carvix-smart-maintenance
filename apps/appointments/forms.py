from django import forms
from django.forms import formset_factory
from django.utils.translation import gettext_lazy as _

from apps.authentication.models import User
from apps.maintenance.models import ServiceType, TechnicianProfile
from apps.inventory.models import SparePart
from apps.vehicles.models import Vehicle

from .models import ServiceSlot
from .selectors import get_available_service_slots


class AppointmentBookingForm(forms.Form):
    vehicle = forms.ModelChoiceField(
        queryset=Vehicle.objects.none(),
        label=_("Vehicle"),
        error_messages={"invalid_choice": _("This vehicle is unavailable. Refresh and try again.")},
    )
    service_type = forms.ModelChoiceField(
        queryset=ServiceType.objects.all(),
        label=_("Service"),
        error_messages={"invalid_choice": _("This service is unavailable. Refresh and try again.")},
    )
    slot = forms.ModelChoiceField(
        queryset=ServiceSlot.objects.none(),
        label=_("Available time slot"),
        error_messages={
            "invalid_choice": _("This time slot is no longer available. Refresh and choose another slot.")
        },
    )

    def __init__(self, *args, owner, initial_vehicle=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["vehicle"].queryset = Vehicle.objects.filter(owner=owner)
        self.fields["slot"].queryset = get_available_service_slots()
        self.available_slots = self.fields["slot"].queryset
        self.has_available_slots = self.available_slots.exists()
        if initial_vehicle is not None and "vehicle" not in self.initial:
            self.initial["vehicle"] = initial_vehicle.pk

        self.fields["slot"].empty_label = _("Choose an available slot")
        self.fields["slot"].help_text = _(
            "Availability may change before the booking is finalized."
        )


class TechnicianAssignmentForm(forms.Form):
    technician = forms.ModelChoiceField(
        queryset=TechnicianProfile.objects.filter(
            user__role=User.Role.TECHNICIAN,
            is_available=True,
        ).select_related("user"),
        label=_("Technician"),
        error_messages={"invalid_choice": _("Choose an available Technician account.")},
    )
    confirm_assignment = forms.BooleanField(
        required=True,
        label=_("I confirm this Technician assignment."),
    )


class MaintenanceCompletionForm(forms.Form):
    mileage_at_service = forms.IntegerField(
        min_value=0,
        label=_("Mileage at service"),
        error_messages={"min_value": _("Mileage cannot be negative.")},
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea,
        label=_("Maintenance notes"),
    )


class SparePartUsageForm(forms.Form):
    spare_part = forms.ModelChoiceField(
        queryset=SparePart.objects.none(),
        required=False,
        label=_("Spare part"),
    )
    quantity_used = forms.IntegerField(
        min_value=1,
        required=False,
        label=_("Quantity used"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["spare_part"].queryset = SparePart.objects.order_by("name", "pk")


SparePartUsageFormSet = formset_factory(
    SparePartUsageForm,
    extra=10,
    max_num=20,
    validate_max=True,
)
