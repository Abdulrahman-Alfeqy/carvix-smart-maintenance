from django import forms

from .models import Vehicle, normalize_license_plate


class VehicleForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = (
            "manufacturer",
            "model",
            "model_year",
            "license_plate",
            "current_mileage",
        )

    def clean_license_plate(self):
        plate = normalize_license_plate(self.cleaned_data["license_plate"])
        duplicates = Vehicle.objects.filter(license_plate__iexact=plate)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(
                "A vehicle with this license plate already exists.",
                code="unique",
            )
        return plate
