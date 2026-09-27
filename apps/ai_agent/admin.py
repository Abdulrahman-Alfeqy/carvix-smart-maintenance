from django.contrib import admin

from apps.authentication.models import User

from .models import AgentActionLog


@admin.register(AgentActionLog)
class AgentActionLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "tool_name", "status", "duration_ms")
    list_filter = ("status", "tool_name", "created_at")
    search_fields = ("tool_name", "user__username", "user__email")
    ordering = ("-created_at", "-id")
    readonly_fields = tuple(
        field.name for field in AgentActionLog._meta.fields
    )

    def has_module_permission(self, request):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMINISTRATOR
            and super().has_module_permission(request)
        )

    def has_view_permission(self, request, obj=None):
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ADMINISTRATOR
            and super().has_view_permission(request, obj)
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
