from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from .sanitization import sanitize_payload


class AgentActionLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILURE = "FAILURE", "Failure"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="agent_action_logs",
    )
    tool_name = models.CharField(max_length=100)
    arguments = models.JSONField()
    result = models.JSONField()
    status = models.CharField(max_length=7, choices=Status.choices)
    duration_ms = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "tool_name", "created_at"),
                name="aal_user_tool_time_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=("SUCCESS", "FAILURE")),
                name="aal_status_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(duration_ms__gte=0),
                name="aal_duration_ck",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        try:
            self.arguments = sanitize_payload(self.arguments)
        except ValidationError as error:
            errors["arguments"] = error
        try:
            self.result = sanitize_payload(self.result)
        except ValidationError as error:
            errors["result"] = error
        if isinstance(self.result, dict):
            success = self.result.get("success")
            if not isinstance(success, bool):
                errors["result"] = "Result must contain a boolean success field."
            elif self.status in self.Status.values:
                expected = self.status == self.Status.SUCCESS
                if success != expected:
                    errors["status"] = "Status must agree with result.success."
        if self.status not in self.Status.values:
            errors["status"] = "Select a valid status."
        if isinstance(self.duration_ms, bool) or not isinstance(self.duration_ms, int) or self.duration_ms < 0:
            errors["duration_ms"] = "Duration must be a nonnegative integer."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tool_name} ({self.status})"
