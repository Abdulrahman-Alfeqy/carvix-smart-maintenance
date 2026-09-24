from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner"
        TECHNICIAN = "TECHNICIAN", "Technician"
        ADMINISTRATOR = "ADMINISTRATOR", "Administrator"

    email = models.EmailField(unique=True)

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.OWNER,
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    role__in=(
                        "OWNER",
                        "TECHNICIAN",
                        "ADMINISTRATOR",
                    )
                ),
                name="authentication_user_valid_role",
            ),
        ]
