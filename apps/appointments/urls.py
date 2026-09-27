from django.urls import path

from .views import (
    AppointmentBookingView,
    AdministratorAppointmentAssignmentListView,
    AdministratorAppointmentAssignmentView,
    TechnicianAppointmentDetailView,
    TechnicianAppointmentListView,
    TechnicianMaintenanceCompletionView,
    TechnicianStartServiceView,
    OwnerAppointmentDetailView,
    OwnerAppointmentListView,
)


app_name = "appointments"

urlpatterns = [
    path(
        "administrator/assignments/",
        AdministratorAppointmentAssignmentListView.as_view(),
        name="administrator-assignment-list",
    ),
    path(
        "administrator/assignments/<int:appointment_pk>/",
        AdministratorAppointmentAssignmentView.as_view(),
        name="administrator-appointment-assign",
    ),
    path(
        "technician/appointments/",
        TechnicianAppointmentListView.as_view(),
        name="technician-appointment-list",
    ),
    path(
        "technician/appointments/<int:pk>/",
        TechnicianAppointmentDetailView.as_view(),
        name="technician-appointment-detail",
    ),
    path(
        "technician/appointments/<int:pk>/start/",
        TechnicianStartServiceView.as_view(),
        name="technician-appointment-start",
    ),
    path(
        "technician/appointments/<int:pk>/complete/",
        TechnicianMaintenanceCompletionView.as_view(),
        name="technician-appointment-complete",
    ),
    path("", OwnerAppointmentListView.as_view(), name="appointment-list"),
    path("<int:pk>/", OwnerAppointmentDetailView.as_view(), name="appointment-detail"),
    path(
        "vehicles/<int:vehicle_pk>/book/",
        AppointmentBookingView.as_view(),
        name="book",
    ),
]
