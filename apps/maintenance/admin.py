from django.contrib import admin

from .models import MaintenancePart, MaintenanceRecord, ServiceType, TechnicianProfile


@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "specialization", "is_available")
    search_fields = ("user__username", "specialization")
    list_filter = ("is_available", "specialization")
    ordering = ("id",)


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "interval_km", "interval_months", "duration_minutes", "price")
    search_fields = ("name", "description")
    list_filter = ("interval_km", "interval_months")
    ordering = ("name",)


@admin.register(MaintenanceRecord)
class MaintenanceRecordAdmin(admin.ModelAdmin):
    list_display = ("vehicle", "service_type", "technician", "appointment", "service_date")
    search_fields = ("vehicle__license_plate", "service_type__name", "technician__user__username")
    list_filter = ("service_type", "service_date")
    ordering = ("-service_date", "-id")


@admin.register(MaintenancePart)
class MaintenancePartAdmin(admin.ModelAdmin):
    list_display = ("maintenance_record", "spare_part", "quantity_used")
    search_fields = ("spare_part__part_number",)
    ordering = ("id",)
