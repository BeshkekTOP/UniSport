from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView
from rest_framework import generics, serializers

from .forms import RegistrationForm
from .models import League, Match, Team, UserProfile


class HomePageView(TemplateView):
    template_name = "leagues/home.html"


def _resolve_user_role(user: User) -> str:
    if user.is_superuser or user.is_staff:
        return "ADMIN"
    if hasattr(user, "profile"):
        return user.profile.role
    return UserProfile.Role.PLAYER


class RegisterView(CreateView):
    template_name = "registration/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("leagues:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        UserProfile.objects.create(user=self.object, role=form.cleaned_data["role"])
        login(self.request, self.object)
        return response


class LeagueListView(ListView):
    model = League
    template_name = "leagues/league_list.html"
    context_object_name = "leagues"

    def get_queryset(self):
        return League.objects.filter(status=League.Status.ACTIVE).select_related("manager")


class MatchScheduleView(TemplateView):
    template_name = "leagues/match_schedule.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["matches"] = (
            Match.objects.filter(date_time__gte=timezone.now())
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        return context


class TeamDetailView(DetailView):
    model = Team
    template_name = "leagues/team_detail.html"
    context_object_name = "team"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["upcoming_matches"] = (
            Match.objects.filter(
                Q(home_team=self.object) | Q(away_team=self.object),
                date_time__gte=timezone.now(),
            )
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        return context


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles: tuple[str, ...] = tuple()

    def test_func(self):
        return _resolve_user_role(self.request.user) in self.allowed_roles

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return redirect("leagues:home")
        return super().handle_no_permission()


class AdminDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_admin.html"
    allowed_roles = ("ADMIN",)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["total_teams"] = Team.objects.count()
        context["total_leagues"] = League.objects.count()
        context["total_matches"] = Match.objects.count()
        context["total_users"] = User.objects.count()
        return context


class ManagerDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_manager.html"
    allowed_roles = ("MANAGER",)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["my_leagues"] = League.objects.filter(manager=self.request.user).order_by("-season", "sport")
        context["upcoming_matches"] = Match.objects.filter(date_time__gte=timezone.now()).order_by("date_time")[:10]
        return context


class CaptainDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_captain.html"
    allowed_roles = ("CAPTAIN",)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        teams = Team.objects.filter(captain=self.request.user).prefetch_related("players")
        context["captain_teams"] = teams
        context["team_matches"] = (
            Match.objects.filter(Q(home_team__in=teams) | Q(away_team__in=teams), date_time__gte=timezone.now())
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        return context


class PlayerDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_player.html"
    allowed_roles = ("PLAYER",)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        teams = Team.objects.filter(players=self.request.user)
        context["my_teams"] = teams
        context["my_matches"] = (
            Match.objects.filter(Q(home_team__in=teams) | Q(away_team__in=teams), date_time__gte=timezone.now())
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        return context


class MatchSerializer(serializers.ModelSerializer):
    home_team = serializers.CharField(source="home_team.name")
    away_team = serializers.CharField(source="away_team.name")

    class Meta:
        model = Match
        fields = (
            "id",
            "home_team",
            "away_team",
            "date_time",
            "location",
            "score_home",
            "score_away",
            "status",
        )


class MatchListApiView(generics.ListAPIView):
    queryset = Match.objects.select_related("home_team", "away_team").order_by("date_time")
    serializer_class = MatchSerializer
