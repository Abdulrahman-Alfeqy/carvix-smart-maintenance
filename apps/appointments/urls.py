from django.urls import path

from .views import AppointmentBookingView


app_name = "appointments"

urlpatterns = [
    path(
        "vehicles/<int:vehicle_pk>/book/",
        AppointmentBookingView.as_view(),
        name="book",
    ),
]
