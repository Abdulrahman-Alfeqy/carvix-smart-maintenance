from django.contrib import admin

from .models import SparePart


@admin.register(SparePart)
class SparePartAdmin(admin.ModelAdmin):
    list_display = ("part_number", "name", "quantity", "minimum_stock", "unit_price")
    search_fields = ("part_number", "name")
    list_filter = ("minimum_stock",)
    ordering = ("name", "id")
