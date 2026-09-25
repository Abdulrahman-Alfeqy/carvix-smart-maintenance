from django.urls import path

from .views import (
    VehicleCreateView,
    VehicleDetailView,
    VehicleListView,
    VehicleUpdateView,
)


app_name = "vehicles"

urlpatterns = [
    path("", VehicleListView.as_view(), name="vehicle-list"),
    path("new/", VehicleCreateView.as_view(), name="vehicle-create"),
    path("<int:pk>/", VehicleDetailView.as_view(), name="vehicle-detail"),
    path("<int:pk>/edit/", VehicleUpdateView.as_view(), name="vehicle-update"),
]
