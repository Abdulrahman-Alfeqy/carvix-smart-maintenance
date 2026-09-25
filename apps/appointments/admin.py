from django.contrib import admin

from .models import Appointment, ServiceSlot


@admin.register(ServiceSlot)
class ServiceSlotAdmin(admin.ModelAdmin):
    list_display = ("start_time", "end_time", "capacity", "is_active")
    search_fields = ()
    list_filter = ("is_active", "start_time")
    ordering = ("start_time", "id")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("id", "vehicle", "service_type", "slot", "technician", "status", "created_at")
    search_fields = ("vehicle__license_plate", "service_type__name", "technician__user__username")
    list_filter = ("status", "booked_by_agent")
    ordering = ("-created_at", "-id")
    readonly_fields = ("created_at",)
