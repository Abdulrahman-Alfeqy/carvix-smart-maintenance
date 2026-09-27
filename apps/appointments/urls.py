from django.urls import path

from .views import (
    AppointmentBookingView,
    OwnerAppointmentDetailView,
    OwnerAppointmentListView,
)


app_name = "appointments"

urlpatterns = [
    path("", OwnerAppointmentListView.as_view(), name="appointment-list"),
    path("<int:pk>/", OwnerAppointmentDetailView.as_view(), name="appointment-detail"),
    path(
        "vehicles/<int:vehicle_pk>/book/",
        AppointmentBookingView.as_view(),
        name="book",
    ),
]
