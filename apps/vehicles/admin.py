from django.contrib import admin

from .models import Vehicle


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ("license_plate", "manufacturer", "model", "model_year", "owner")
    search_fields = ("license_plate", "manufacturer", "model")
    list_filter = ("manufacturer", "model_year")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_at",)
