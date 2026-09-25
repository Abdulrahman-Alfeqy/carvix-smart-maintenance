from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.authentication.models import User

from .forms import VehicleForm
from .models import Vehicle


class OwnerRequiredMixin(UserPassesTestMixin):
    """Restrict these views to the CARVIX Owner role."""

    def test_func(self):
        return self.request.user.role == User.Role.OWNER


class VehicleListView(LoginRequiredMixin, OwnerRequiredMixin, ListView):
    model = Vehicle
    template_name = "vehicles/vehicle_list.html"
    context_object_name = "vehicles"
    login_url = reverse_lazy("authentication:login")

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user)


class VehicleCreateView(LoginRequiredMixin, OwnerRequiredMixin, CreateView):
    model = Vehicle
    form_class = VehicleForm
    template_name = "vehicles/vehicle_form.html"
    success_url = reverse_lazy("vehicles:vehicle-list")
    login_url = reverse_lazy("authentication:login")

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)


class VehicleDetailView(LoginRequiredMixin, OwnerRequiredMixin, DetailView):
    model = Vehicle
    template_name = "vehicles/vehicle_detail.html"
    context_object_name = "vehicle"
    login_url = reverse_lazy("authentication:login")

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user)


class VehicleUpdateView(LoginRequiredMixin, OwnerRequiredMixin, UpdateView):
    model = Vehicle
    form_class = VehicleForm
    template_name = "vehicles/vehicle_form.html"
    context_object_name = "vehicle"
    success_url = reverse_lazy("vehicles:vehicle-list")
    login_url = reverse_lazy("authentication:login")

    def get_queryset(self):
        return Vehicle.objects.filter(owner=self.request.user)
