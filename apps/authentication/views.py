from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse_lazy
from django.views.generic import TemplateView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.authentication.forms import RegistrationForm, ProfileEditForm
from apps.authentication.models import User


class RegisterView(SuccessMessageMixin, TemplateView):
    template_name = "authentication/register.html"
    form_class = RegistrationForm
    success_message = "Registration successful. Welcome to CARVIX!"
    success_url = reverse_lazy("authentication:profile")

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return self.redirect_to_profile()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return self.redirect_to_profile()
        form = self.form_class(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return self.get_success_response()
        return self.render_to_response(self.get_context_data(form=form))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if "form" not in context:
            context["form"] = self.form_class()
        return context

    def get_success_response(self):
        from django.shortcuts import redirect
        from django.contrib import messages
        messages.success(self.request, self.success_message)
        return redirect(self.success_url)

    def redirect_to_profile(self):
        from django.shortcuts import redirect
        return redirect("authentication:profile")


class CustomLoginView(LoginView):
    template_name = "authentication/login.html"
    redirect_authenticated_user = True
    next_page = reverse_lazy("authentication:profile")


class CustomLogoutView(LogoutView):
    next_page = reverse_lazy("authentication:login")
    http_method_names = ["post", "options"]


class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "authentication/profile.html"
    login_url = reverse_lazy("authentication:login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["user"] = self.request.user
        return context


class ProfileEditView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = ProfileEditForm
    template_name = "authentication/profile_edit.html"
    success_message = "Profile updated successfully."
    success_url = reverse_lazy("authentication:profile")
    login_url = reverse_lazy("authentication:login")

    def get_object(self, queryset=None):
        return self.request.user
