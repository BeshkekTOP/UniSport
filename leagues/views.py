import csv
import io
import os
import tempfile
from collections import Counter

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.contrib.auth.views import PasswordChangeView, PasswordResetView
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db.models import Count, F, Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.encoding import force_bytes
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    FormView,
    ListView,
    TemplateView,
    UpdateView,
)
from rest_framework import generics, serializers
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .forms import (
    AnnouncementForm,
    AttendanceForm,
    AdminUserCreateForm,
    AdminUserUpdateForm,
    CoachAssignForm,
    MatchGoalEventForm,
    MatchCreateForm,
    MatchResultForm,
    ProfileForm,
    RegistrationForm,
    UserPasswordChangeForm,
    LeagueForm,
    TeamForm,
    UserRoleForm,
)
from .models import (
    AuditLog,
    Announcement,
    CoachAssignment,
    CoachRosterAction,
    GoalEvent,
    League,
    Match,
    MatchMVPVote,
    MatchParticipation,
    Notification,
    PlayerAttendance,
    Team,
    TeamJoinRequest,
    UserProfile,
)


# ─── helpers ────────────────────────────────────────────────────────

def _resolve_user_role(user: User) -> str:
    """Суперпользователь — админ. Менеджер/тренер из профиля важнее is_staff.
    Игрок со staff остаётся админом интерфейса (типичный сотрудник с доступом в Django Admin)."""
    if user.is_superuser:
        return "ADMIN"
    if hasattr(user, "profile"):
        r = user.profile.role
        if r == UserProfile.Role.COACH:
            return "COACH"
        if r == UserProfile.Role.MANAGER:
            return "MANAGER"
    if user.is_staff:
        return "ADMIN"
    if hasattr(user, "profile") and user.profile.role == UserProfile.Role.PLAYER:
        return UserProfile.Role.PLAYER
    return UserProfile.Role.PLAYER


def _leagues_for_match_or_announcement(user: User):
    """Лиги в формах матча и объявления: админ — все иначе — лиги, где user — менеджер."""
    ordered = League.objects.all().order_by("-season", "sport")
    if user.is_superuser or _resolve_user_role(user) == "ADMIN":
        return ordered
    if _resolve_user_role(user) == "MANAGER":
        managed = ordered.filter(manager=user)
        if managed.exists():
            return managed
        return League.objects.none()
    return League.objects.none()


def _manager_has_leagues(user: User) -> bool:
    return League.objects.filter(manager=user).exists()


def _notify(user, message, link=""):
    Notification.objects.create(user=user, message=message, link=link)


def _user_in_league(user: User, league: League) -> bool:
    if not user.is_authenticated:
        return False
    return (
        Team.objects.filter(leagues=league)
        .filter(Q(players=user) | Q(captain=user))
        .exists()
    )


def _player_goal_count(user: User) -> int:
    return GoalEvent.objects.filter(scorer=user).count()


def _player_mvp_count(user: User) -> int:
    return MatchMVPVote.objects.filter(candidate=user).count()


def _player_rating(user: User) -> float:
    goals = _player_goal_count(user)
    mvp_votes = _player_mvp_count(user)
    # 10-балльная шкала: голы дают динамику, MVP даёт повышенный вклад.
    raw = 4.0 + (goals * 0.25) + (mvp_votes * 1.1)
    return round(min(10.0, raw), 2)


def _faculty_label(code: str) -> str:
    return dict(Team.Faculty.choices).get(code, code or "—")


def _course_label(code: str) -> str:
    return dict(UserProfile.Course.choices).get(code, code or "—")


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles: tuple[str, ...] = ()

    def test_func(self):
        return _resolve_user_role(self.request.user) in self.allowed_roles

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            return redirect("leagues:home")
        return super().handle_no_permission()


# ─── context processor ─────────────────────────────────────────────

def user_context(request):
    ctx = {}
    if request.user.is_authenticated:
        ctx["user_role"] = _resolve_user_role(request.user)
        ctx["unread_count"] = Notification.objects.filter(user=request.user, is_read=False).count()
    return ctx


# ─── public pages ──────────────────────────────────────────────────

class HomePageView(TemplateView):
    template_name = "leagues/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["active_leagues"] = League.objects.filter(status=League.Status.ACTIVE)[:6]
        ctx["upcoming_matches"] = (
            Match.objects.filter(date_time__gte=timezone.now())
            .select_related("home_team", "away_team")[:5]
        )
        ctx["stat_active_leagues"] = League.objects.filter(status=League.Status.ACTIVE).count()
        ctx["stat_teams"] = Team.objects.count()
        ctx["stat_upcoming"] = Match.objects.filter(date_time__gte=timezone.now()).count()
        return ctx


class SearchView(TemplateView):
    template_name = "leagues/search.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        q = self.request.GET.get("q", "").strip()
        ctx["query"] = q
        if not q:
            ctx["leagues"] = League.objects.none()
            ctx["teams"] = Team.objects.none()
            ctx["matches"] = Match.objects.none()
            return ctx

        sport_q = Q()
        for code, label in League.Sport.choices:
            if q.lower() in label.lower():
                sport_q |= Q(sport=code)

        ctx["leagues"] = (
            League.objects.filter(Q(season__icontains=q) | sport_q)
            .select_related("manager")[:20]
        )
        ctx["teams"] = Team.objects.filter(name__icontains=q).select_related("captain")[:20]
        ctx["matches"] = (
            Match.objects.filter(
                Q(home_team__name__icontains=q) | Q(away_team__name__icontains=q)
            )
            .select_related("home_team", "away_team", "league")
            .order_by("date_time")[:20]
        )
        return ctx


class AboutView(TemplateView):
    template_name = "leagues/about.html"


class RegisterView(CreateView):
    template_name = "registration/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("leagues:home")

    def form_valid(self, form):
        response = super().form_valid(form)
        UserProfile.objects.create(
            user=self.object,
            role=UserProfile.Role.PLAYER,
            faculty=form.cleaned_data["faculty"],
            study_group=form.cleaned_data["study_group"],
            course=form.cleaned_data["course"],
            age=form.cleaned_data["age"],
        )
        login(self.request, self.object)
        return response


class UserPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "registration/password_change_form.html"
    form_class = UserPasswordChangeForm
    success_url = reverse_lazy("leagues:profile")

    def form_valid(self, form):
        messages.success(self.request, "Пароль успешно изменён.")
        return super().form_valid(form)


# ─── leagues ───────────────────────────────────────────────────────

class LeagueListView(ListView):
    model = League
    template_name = "leagues/league_list.html"
    context_object_name = "leagues"

    def get_queryset(self):
        qs = League.objects.select_related("manager")
        status = self.request.GET.get("status")
        if status in dict(League.Status.choices):
            qs = qs.filter(status=status)
        return qs


class LeagueDetailView(DetailView):
    model = League
    template_name = "leagues/league_detail.html"
    context_object_name = "league"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = League.Status.choices
        match_team_ids = set(
            Match.objects.filter(league=self.object).values_list("home_team_id", flat=True)
        ) | set(
            Match.objects.filter(league=self.object).values_list("away_team_id", flat=True)
        )
        team_filter = Q(leagues=self.object)
        if match_team_ids:
            team_filter = team_filter | Q(pk__in=match_team_ids)
        ctx["teams"] = Team.objects.filter(team_filter).distinct().order_by("name")
        course_sections = {}
        for t in ctx["teams"]:
            course_sections.setdefault(_course_label(t.course), []).append(t)
        ctx["course_sections"] = course_sections
        ctx["matches"] = self.object.matches.select_related("home_team", "away_team")
        ctx["announcements"] = self.object.announcements.all()[:10]
        # standings
        standings = []
        for team in ctx["teams"]:
            wins = Match.objects.filter(
                league=self.object, status=Match.Status.COMPLETED
            ).filter(
                Q(home_team=team, score_home__gt=F("score_away"))
                | Q(away_team=team, score_away__gt=F("score_home"))
            ).count()
            losses = Match.objects.filter(
                league=self.object, status=Match.Status.COMPLETED
            ).filter(
                Q(home_team=team, score_home__lt=F("score_away"))
                | Q(away_team=team, score_away__lt=F("score_home"))
            ).count()
            played = wins + losses
            standings.append({"team": team, "played": played, "wins": wins, "losses": losses, "points": wins * 2})
        standings.sort(key=lambda s: s["points"], reverse=True)
        ctx["standings"] = standings
        user = self.request.user
        league = self.object
        ctx["user_in_league"] = _user_in_league(user, league) if user.is_authenticated else False
        ctx["my_join_request"] = None
        if user.is_authenticated and _resolve_user_role(user) == "PLAYER":
            ctx["my_join_request"] = TeamJoinRequest.objects.filter(user=user, league=league).first()
        ctx["pending_join_requests"] = TeamJoinRequest.objects.none()
        if user.is_authenticated:
            ctx["pending_join_requests"] = (
                TeamJoinRequest.objects.filter(
                    league=league,
                    status=TeamJoinRequest.Status.PENDING,
                    team__captain=user,
                )
                .select_related("user", "team")
                .order_by("created_at")
            )
        return ctx


# ─── matches ───────────────────────────────────────────────────────

class MatchScheduleView(TemplateView):
    template_name = "leagues/match_schedule.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = (
            Match.objects.all()
            .select_related("home_team", "away_team", "league")
            .order_by("-date_time")
        )
        league_id = self.request.GET.get("league")
        if league_id:
            qs = qs.filter(league_id=league_id)
        status = self.request.GET.get("status")
        if status in dict(Match.Status.choices):
            qs = qs.filter(status=status)
        team_id = self.request.GET.get("team")
        if team_id:
            qs = qs.filter(Q(home_team_id=team_id) | Q(away_team_id=team_id))
        ctx["matches"] = qs
        ctx["filter_leagues"] = League.objects.order_by("-season")[:100]
        ctx["filter_teams"] = Team.objects.order_by("name")[:200]
        ctx["status_choices"] = Match.Status.choices
        ctx["match_days"] = sorted({m.date_time.date() for m in qs[:200]})
        return ctx


class MatchDetailView(DetailView):
    model = Match
    template_name = "leagues/match_detail.html"
    context_object_name = "match"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["participations"] = self.object.participations.select_related("team", "confirmed_by")
        ctx["attendances"] = self.object.attendances.select_related("player", "team")
        ctx["goal_events"] = self.object.goal_events.select_related("scorer", "team")
        is_manager_or_admin = self.request.user.is_authenticated and _resolve_user_role(self.request.user) in {"MANAGER", "ADMIN"}
        can_manage_match = is_manager_or_admin and (
            _resolve_user_role(self.request.user) == "ADMIN"
            or (self.object.league and self.object.league.manager_id == self.request.user.id)
        )
        ctx["can_manage_match"] = can_manage_match
        players_qs = User.objects.filter(
            attendances__match=self.object,
            attendances__status=PlayerAttendance.Reason.PRESENT,
        ).distinct().order_by("username")
        if not players_qs.exists():
            players_qs = User.objects.filter(
                Q(teams=self.object.home_team) | Q(teams=self.object.away_team)
            ).distinct().order_by("username")
        ctx["goal_form"] = MatchGoalEventForm(players_queryset=players_qs)
        window_start = self.object.completed_at or self.object.date_time
        vote_window_open = (
            self.object.status == Match.Status.COMPLETED
            and timezone.now() <= (window_start + timezone.timedelta(hours=24))
        )
        is_player = self.request.user.is_authenticated and _resolve_user_role(self.request.user) == "PLAYER"
        ctx["can_vote_mvp"] = is_player and vote_window_open and _user_in_league(
            self.request.user, self.object.league
        ) if self.object.league else False
        ctx["mvp_candidates"] = players_qs
        ctx["my_mvp_vote"] = None
        if is_player:
            ctx["my_mvp_vote"] = MatchMVPVote.objects.filter(
                match=self.object, voter=self.request.user
            ).select_related("candidate").first()
        ctx["mvp_leader"] = (
            MatchMVPVote.objects.filter(match=self.object)
            .values("candidate")
            .annotate(votes=Count("id"))
            .order_by("-votes")
            .first()
        )
        if ctx["mvp_leader"]:
            ctx["mvp_player"] = User.objects.filter(pk=ctx["mvp_leader"]["candidate"]).first()
        return ctx


class MatchCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ("MANAGER", "ADMIN")
    model = Match
    form_class = MatchCreateForm
    template_name = "leagues/match_form.html"

    def dispatch(self, request, *args, **kwargs):
        if _resolve_user_role(request.user) == "MANAGER" and not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def _locked_league(self):
        league_id = self.request.GET.get("league") or self.request.POST.get("league")
        if not league_id:
            if _resolve_user_role(self.request.user) == "MANAGER":
                managed = League.objects.filter(manager=self.request.user).order_by("-season", "sport")
                if managed.count() == 1:
                    return managed.first()
            return None
        role = _resolve_user_role(self.request.user)
        if role == "MANAGER":
            return League.objects.filter(pk=league_id, manager=self.request.user).first()
        base_qs = _leagues_for_match_or_announcement(self.request.user)
        return base_qs.filter(pk=league_id).first()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        locked_league = self._locked_league()
        if locked_league:
            kwargs["league_queryset"] = League.objects.filter(pk=locked_league.pk)
        else:
            kwargs["league_queryset"] = _leagues_for_match_or_announcement(self.request.user)
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        locked_league = self._locked_league()
        if locked_league:
            initial["league"] = locked_league.pk
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["locked_league"] = self._locked_league()
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        match = self.object
        MatchParticipation.objects.create(match=match, team=match.home_team)
        MatchParticipation.objects.create(match=match, team=match.away_team)
        # notify captains
        for team in (match.home_team, match.away_team):
            if team.captain:
                _notify(
                    team.captain,
                    f"Новый матч: {match.home_team} vs {match.away_team} ({match.date_time:%d.%m.%Y %H:%M})",
                    reverse("leagues:match_detail", args=[match.pk]),
                )
        messages.success(self.request, "Матч создан.")
        return response

    def get_success_url(self):
        return reverse("leagues:match_detail", args=[self.object.pk])


class MatchResultView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER", "ADMIN")

    def post(self, request, pk):
        match = get_object_or_404(Match, pk=pk)
        if _resolve_user_role(request.user) == "MANAGER":
            if not match.league or match.league.manager_id != request.user.id:
                raise PermissionDenied()
        form = MatchResultForm(request.POST)
        if form.is_valid():
            match.score_home = form.cleaned_data["score_home"]
            match.score_away = form.cleaned_data["score_away"]
            match.status = Match.Status.COMPLETED
            match.completed_at = timezone.now()
            match.save()
            messages.success(request, "Результат сохранён.")
        return redirect("leagues:match_detail", pk=pk)


class MatchGoalEventCreateView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER", "ADMIN")

    def post(self, request, pk):
        match = get_object_or_404(Match, pk=pk)
        if _resolve_user_role(request.user) == "MANAGER":
            if not match.league or match.league.manager_id != request.user.id:
                raise PermissionDenied()
        players_qs = User.objects.filter(
            Q(teams=match.home_team) | Q(teams=match.away_team)
        ).distinct()
        form = MatchGoalEventForm(request.POST, players_queryset=players_qs)
        if not form.is_valid():
            messages.error(request, "Проверьте данные по голу.")
            return redirect("leagues:match_detail", pk=pk)
        scorer = form.cleaned_data["scorer"]
        minute = form.cleaned_data["minute"]
        if match.home_team.players.filter(pk=scorer.pk).exists():
            team = match.home_team
            score_home_inc = 1
            score_away_inc = 0
        elif match.away_team.players.filter(pk=scorer.pk).exists():
            team = match.away_team
            score_home_inc = 0
            score_away_inc = 1
        else:
            messages.error(request, "Игрок не участвует в этом матче.")
            return redirect("leagues:match_detail", pk=pk)
        GoalEvent.objects.create(
            match=match, team=team, scorer=scorer, minute=minute, created_by=request.user
        )
        match.score_home = (match.score_home or 0) + score_home_inc
        match.score_away = (match.score_away or 0) + score_away_inc
        match.save(update_fields=["score_home", "score_away"])
        messages.success(request, "Гол добавлен и счёт обновлён.")
        return redirect("leagues:match_detail", pk=pk)


class MatchStatusUpdateView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER", "ADMIN")

    def post(self, request, pk):
        match = get_object_or_404(Match, pk=pk)
        if _resolve_user_role(request.user) == "MANAGER":
            if not match.league or match.league.manager_id != request.user.id:
                raise PermissionDenied()
        action = request.POST.get("action")
        if action == "start":
            match.status = Match.Status.IN_PROGRESS
            match.save(update_fields=["status"])
            messages.success(request, "Матч переведён в статус «В процессе».")
        elif action == "finish":
            match.status = Match.Status.COMPLETED
            if not match.completed_at:
                match.completed_at = timezone.now()
                match.save(update_fields=["status", "completed_at"])
            else:
                match.save(update_fields=["status"])
            messages.success(request, "Матч завершён.")
        return redirect("leagues:match_detail", pk=pk)


class MatchMVPVoteView(RoleRequiredMixin, View):
    allowed_roles = ("PLAYER",)

    def post(self, request, pk):
        match = get_object_or_404(Match, pk=pk)
        if match.status != Match.Status.COMPLETED:
            messages.error(request, "Голосование доступно только после завершения матча.")
            return redirect("leagues:match_detail", pk=pk)
        window_start = match.completed_at or match.date_time
        if timezone.now() > (window_start + timezone.timedelta(hours=24)):
            messages.error(request, "Окно голосования за MVP закрыто.")
            return redirect("leagues:match_detail", pk=pk)
        if match.league and not _user_in_league(request.user, match.league):
            messages.error(request, "Вы не участник этой лиги.")
            return redirect("leagues:match_detail", pk=pk)
        candidate = get_object_or_404(User, pk=request.POST.get("candidate_id"))
        allowed_candidates = User.objects.filter(
            attendances__match=match,
            attendances__status=PlayerAttendance.Reason.PRESENT,
        ).distinct()
        if not allowed_candidates.exists():
            allowed_candidates = User.objects.filter(
                Q(teams=match.home_team) | Q(teams=match.away_team)
            ).distinct()
        if not allowed_candidates.filter(pk=candidate.pk).exists():
            messages.error(request, "Нельзя голосовать за этого пользователя.")
            return redirect("leagues:match_detail", pk=pk)
        if MatchMVPVote.objects.filter(match=match, voter=request.user).exists():
            messages.error(request, "Вы уже голосовали за MVP в этом матче.")
            return redirect("leagues:match_detail", pk=pk)
        MatchMVPVote.objects.create(match=match, voter=request.user, candidate=candidate)
        messages.success(request, "Ваш голос за MVP сохранён.")
        return redirect("leagues:match_detail", pk=pk)


# ─── teams ─────────────────────────────────────────────────────────

class TeamDetailView(DetailView):
    model = Team
    template_name = "leagues/team_detail.html"
    context_object_name = "team"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["upcoming_matches"] = (
            Match.objects.filter(
                Q(home_team=self.object) | Q(away_team=self.object),
                date_time__gte=timezone.now(),
            )
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        completed = Match.objects.filter(
            Q(home_team=self.object) | Q(away_team=self.object),
            status=Match.Status.COMPLETED,
        ).select_related("home_team", "away_team")
        ctx["completed_matches"] = completed
        wins = 0
        for m in completed:
            if (m.home_team == self.object and (m.score_home or 0) > (m.score_away or 0)) or \
               (m.away_team == self.object and (m.score_away or 0) > (m.score_home or 0)):
                wins += 1
        ctx["stats"] = {"played": completed.count(), "wins": wins, "losses": completed.count() - wins}
        ctx["team_leagues"] = self.object.leagues.all()
        return ctx


class TeamCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ("MANAGER", "ADMIN")
    model = Team
    form_class = TeamForm
    template_name = "leagues/team_form.html"

    def dispatch(self, request, *args, **kwargs):
        if _resolve_user_role(request.user) == "MANAGER" and not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        role = _resolve_user_role(self.request.user)
        league_queryset = League.objects.none()
        if role == "ADMIN":
            league_queryset = League.objects.order_by("-season", "sport")
        elif role == "MANAGER":
            league_queryset = League.objects.filter(manager=self.request.user).order_by("-season", "sport")
        kwargs["league_queryset"] = league_queryset
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        league_id = self.request.GET.get("league")
        if league_id:
            initial["league"] = league_id
        return initial

    def form_valid(self, form):
        if _resolve_user_role(self.request.user) == "MANAGER" and not form.cleaned_data.get("league"):
            form.add_error("league", "Для менеджера выбор лиги обязателен.")
            return self.form_invalid(form)
        response = super().form_valid(form)
        league = form.cleaned_data.get("league")
        if league:
            self.object.leagues.add(league)
        return response

    def get_success_url(self):
        return reverse("leagues:team_detail", args=[self.object.pk])


class TeamUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ("MANAGER", "ADMIN")
    model = Team
    form_class = TeamForm
    template_name = "leagues/team_form.html"

    def dispatch(self, request, *args, **kwargs):
        if _resolve_user_role(request.user) == "MANAGER" and not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        team = super().get_object(queryset)
        if _resolve_user_role(self.request.user) == "MANAGER":
            managed = League.objects.filter(manager=self.request.user)
            if not team.leagues.filter(pk__in=managed.values_list("pk", flat=True)).exists():
                raise PermissionDenied()
        return team

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if _resolve_user_role(self.request.user) == "MANAGER":
            kwargs["league_queryset"] = League.objects.filter(manager=self.request.user).order_by("-season", "sport")
        else:
            kwargs["league_queryset"] = League.objects.order_by("-season", "sport")
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        initial["league"] = self.object.leagues.first()
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        league = form.cleaned_data.get("league")
        if league:
            self.object.leagues.add(league)
        return response

    def get_success_url(self):
        return reverse("leagues:team_detail", args=[self.object.pk])


class TeamDeleteView(RoleRequiredMixin, DeleteView):
    allowed_roles = ("MANAGER", "ADMIN")
    model = Team
    template_name = "leagues/confirm_delete.html"
    success_url = reverse_lazy("leagues:team_browse")

    def dispatch(self, request, *args, **kwargs):
        if _resolve_user_role(request.user) == "MANAGER" and not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        team = super().get_object(queryset)
        if _resolve_user_role(self.request.user) == "MANAGER":
            managed = League.objects.filter(manager=self.request.user)
            if not team.leagues.filter(pk__in=managed.values_list("pk", flat=True)).exists():
                raise PermissionDenied()
        return team

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["entity_name"] = f"команду «{self.object.name}»"
        return ctx


# ─── catalog: players, coaches, teams ──────────────────────────────

class PlayerListView(ListView):
    template_name = "leagues/player_list.html"
    context_object_name = "players"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["faculty_choices"] = Team.Faculty.choices
        for p in ctx["players"]:
            if hasattr(p, "profile") and p.profile.faculty:
                p.display_faculty = _faculty_label(p.profile.faculty)
            else:
                first_team = p.teams.first()
                p.display_faculty = first_team.get_faculty_display() if first_team else "—"
            p.display_age = getattr(getattr(p, "profile", None), "age", None) or "—"
        return ctx

    def get_queryset(self):
        qs = (
            User.objects.filter(profile__role=UserProfile.Role.PLAYER)
            .filter(is_staff=False, is_superuser=False)
            .select_related("profile")
        )
        faculty = self.request.GET.get("faculty")
        if faculty in {c[0] for c in Team.Faculty.choices}:
            qs = qs.filter(profile__faculty=faculty)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )
        return qs.order_by("username")


class PlayerDetailView(DetailView):
    model = User
    template_name = "leagues/person_detail.html"
    context_object_name = "person"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not hasattr(obj, "profile"):
            raise Http404()
        if obj.profile.role != UserProfile.Role.PLAYER:
            raise Http404()
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["is_coach"] = False
        ctx["member_teams"] = self.object.teams.prefetch_related("leagues").all()
        ctx["goals_count"] = _player_goal_count(self.object)
        ctx["mvp_count"] = _player_mvp_count(self.object)
        ctx["rating_10"] = _player_rating(self.object)
        if hasattr(self.object, "profile") and self.object.profile.faculty:
            ctx["display_faculty"] = _faculty_label(self.object.profile.faculty)
        else:
            first_team = self.object.teams.first()
            ctx["display_faculty"] = first_team.get_faculty_display() if first_team else "—"
        ctx["display_course"] = _course_label(getattr(self.object.profile, "course", ""))
        ctx["display_age"] = getattr(self.object.profile, "age", None) or "—"
        return ctx


class CoachListView(ListView):
    template_name = "leagues/coach_list.html"
    context_object_name = "coaches"
    paginate_by = 30

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["faculty_choices"] = Team.Faculty.choices
        for c in ctx["coaches"]:
            if hasattr(c, "profile") and c.profile.faculty:
                c.display_faculty = _faculty_label(c.profile.faculty)
            else:
                first_team = c.captained_teams.first()
                c.display_faculty = first_team.get_faculty_display() if first_team else "—"
            c.display_age = getattr(getattr(c, "profile", None), "age", None) or "—"
        return ctx

    def get_queryset(self):
        qs = (
            User.objects.filter(
                Q(profile__role=UserProfile.Role.COACH) | Q(captained_teams__isnull=False),
            )
            .exclude(is_superuser=True)
            .distinct()
            .select_related("profile")
        )
        faculty = self.request.GET.get("faculty")
        if faculty in {c[0] for c in Team.Faculty.choices}:
            qs = qs.filter(
                Q(profile__faculty=faculty) | Q(captained_teams__faculty=faculty)
            ).distinct()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )
        return qs.order_by("username")


class CoachDetailView(DetailView):
    model = User
    template_name = "leagues/person_detail.html"
    context_object_name = "person"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        is_coach_role = (
            hasattr(obj, "profile") and obj.profile.role == UserProfile.Role.COACH
        )
        if not is_coach_role and not obj.captained_teams.exists():
            raise Http404()
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["is_coach"] = True
        ctx["member_teams"] = self.object.captained_teams.prefetch_related("leagues").all()
        ctx["goals_count"] = _player_goal_count(self.object)
        ctx["mvp_count"] = _player_mvp_count(self.object)
        ctx["rating_10"] = _player_rating(self.object)
        if hasattr(self.object, "profile") and self.object.profile.faculty:
            ctx["display_faculty"] = _faculty_label(self.object.profile.faculty)
        else:
            first_team = self.object.captained_teams.first()
            ctx["display_faculty"] = first_team.get_faculty_display() if first_team else "—"
        ctx["display_course"] = _course_label(getattr(self.object.profile, "course", ""))
        ctx["display_age"] = getattr(self.object.profile, "age", None) or "—"
        ctx["coach_bio"] = (getattr(self.object.profile, "bio", "") or "").strip()
        viewer_role = _resolve_user_role(self.request.user) if self.request.user.is_authenticated else ""
        ctx["can_edit_bio"] = viewer_role in {"ADMIN", "MANAGER"} or self.request.user.id == self.object.id
        return ctx


class TeamBrowseListView(ListView):
    model = Team
    template_name = "leagues/team_browse_list.html"
    context_object_name = "teams"
    paginate_by = 30

    def get_queryset(self):
        qs = Team.objects.select_related("captain").prefetch_related("leagues").annotate(player_count=Count("players"))
        league_id = self.request.GET.get("league")
        if league_id:
            qs = qs.filter(leagues__id=league_id)
        faculty = self.request.GET.get("faculty")
        if faculty in {c[0] for c in Team.Faculty.choices}:
            qs = qs.filter(faculty=faculty)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        return qs.order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_leagues"] = League.objects.order_by("-season")[:80]
        ctx["faculty_choices"] = Team.Faculty.choices
        for t in ctx["teams"]:
            t.sport_preview = ", ".join(sorted({l.get_sport_display() for l in t.leagues.all()})) or "—"
        return ctx


class MatchListAllView(ListView):
    model = Match
    template_name = "leagues/match_list_all.html"
    context_object_name = "matches"
    paginate_by = 40

    def get_queryset(self):
        qs = Match.objects.select_related("home_team", "away_team", "league").order_by("-date_time")
        league_id = self.request.GET.get("league")
        if league_id:
            qs = qs.filter(league_id=league_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_leagues"] = League.objects.order_by("-season")[:80]
        return ctx


# ─── admin users ───────────────────────────────────────────────────

class AdminUserListView(RoleRequiredMixin, ListView):
    allowed_roles = ("ADMIN",)
    model = User
    template_name = "leagues/admin_user_list.html"
    context_object_name = "users_list"
    paginate_by = 40

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["role_choices"] = UserProfile.Role.choices
        return ctx

    def get_queryset(self):
        qs = User.objects.select_related("profile").order_by("username")
        role = self.request.GET.get("role")
        if role in {c[0] for c in UserProfile.Role.choices}:
            qs = qs.filter(profile__role=role)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
        return qs


class AdminUserRoleView(RoleRequiredMixin, UpdateView):
    allowed_roles = ("ADMIN",)
    model = UserProfile
    form_class = UserRoleForm
    template_name = "leagues/admin_user_role.html"
    context_object_name = "profile_obj"

    def get_object(self, queryset=None):
        user = get_object_or_404(User, pk=self.kwargs["pk"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    def form_valid(self, form):
        messages.success(self.request, "Роль обновлена.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("leagues:admin_users")


# ─── join requests & roster ────────────────────────────────────────

class TeamApplyView(LoginRequiredMixin, View):
    def post(self, request, league_pk, team_pk):
        league = get_object_or_404(League, pk=league_pk)
        team = get_object_or_404(Team, pk=team_pk)
        if not league.teams.filter(pk=team_pk).exists():
            messages.error(request, "Команда не участвует в этой лиге.")
            return redirect("leagues:league_detail", pk=league_pk)
        if _resolve_user_role(request.user) != "PLAYER":
            messages.error(request, "Заявки подают только игроки.")
            return redirect("leagues:league_detail", pk=league_pk)
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        if profile.faculty and team.faculty != profile.faculty:
            messages.error(request, "Нельзя подать заявку в команду другого факультета.")
            return redirect("leagues:league_detail", pk=league_pk)
        if profile.course and team.course and team.course != profile.course:
            messages.error(request, "Нельзя подать заявку в команду другого курса.")
            return redirect("leagues:league_detail", pk=league_pk)
        if _user_in_league(request.user, league):
            messages.error(request, "Вы уже состоите в команде этой лиги.")
            return redirect("leagues:league_detail", pk=league_pk)
        TeamJoinRequest.objects.update_or_create(
            user=request.user,
            league=league,
            defaults={
                "team": team,
                "status": TeamJoinRequest.Status.PENDING,
                "processed_at": None,
            },
        )
        messages.success(request, "Заявка отправлена тренеру.")
        if team.captain:
            _notify(
                team.captain,
                f"Заявка от {request.user.username} в команду «{team.name}» ({league})",
                reverse("leagues:league_detail", args=[league_pk]),
            )
        return redirect("leagues:league_detail", pk=league_pk)


class PlayerJoinRequestCancelView(RoleRequiredMixin, View):
    allowed_roles = ("PLAYER",)

    def post(self, request, pk):
        join_req = get_object_or_404(TeamJoinRequest, pk=pk, user=request.user)
        if join_req.status != TeamJoinRequest.Status.PENDING:
            messages.error(request, "Можно отменить только активную заявку.")
            return redirect("leagues:role_player")
        join_req.delete()
        messages.success(request, "Заявка отменена.")
        return redirect("leagues:role_player")


class CoachJoinRequestView(LoginRequiredMixin, View):
    def post(self, request, pk):
        join_req = get_object_or_404(TeamJoinRequest, pk=pk)
        if join_req.team.captain_id != request.user.id:
            messages.error(request, "Недостаточно прав.")
            return redirect("leagues:home")
        action = request.POST.get("action")
        if action == "approve":
            if _user_in_league(join_req.user, join_req.league):
                messages.error(request, "Игрок уже в команде этой лиги.")
            else:
                join_req.team.players.add(join_req.user)
                join_req.status = TeamJoinRequest.Status.APPROVED
                join_req.processed_at = timezone.now()
                join_req.save()
                _notify(
                    join_req.user,
                    f"Вас приняли в команду «{join_req.team.name}» ({join_req.league})",
                    reverse("leagues:team_detail", args=[join_req.team_id]),
                )
                messages.success(request, "Игрок принят в команду.")
        elif action == "reject":
            join_req.status = TeamJoinRequest.Status.REJECTED
            join_req.processed_at = timezone.now()
            join_req.save()
            _notify(
                join_req.user,
                f"Заявка в «{join_req.team.name}» отклонена",
                reverse("leagues:league_detail", args=[join_req.league_id]),
            )
            messages.info(request, "Заявка отклонена.")
        return redirect("leagues:league_detail", pk=join_req.league_id)


class ManagerCoachAssignView(RoleRequiredMixin, FormView):
    allowed_roles = ("MANAGER",)
    template_name = "leagues/manager_coach_assign.html"
    form_class = CoachAssignForm
    success_url = reverse_lazy("leagues:manager_coach_assign")

    def dispatch(self, request, *args, **kwargs):
        if not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["manager"] = self.request.user
        kwargs["league_queryset"] = (
            League.objects.filter(manager=self.request.user).order_by("-season", "sport")
        )
        return kwargs

    def form_valid(self, form):
        league = form.cleaned_data["league"]
        team = form.cleaned_data["team"]
        coach = form.cleaned_data["coach"]
        if self.request.user != league.manager:
            messages.error(self.request, "Это не ваша лига.")
            return self.form_invalid(form)
        if not league.teams.filter(pk=team.pk).exists():
            messages.error(self.request, "Команда не в выбранной лиге.")
            return self.form_invalid(form)
        team.captain = coach
        team.save(update_fields=["captain"])
        profile, _ = UserProfile.objects.get_or_create(user=coach)
        if profile.role == UserProfile.Role.PLAYER:
            profile.role = UserProfile.Role.COACH
            profile.save(update_fields=["role"])
        CoachAssignment.objects.update_or_create(
            user=coach,
            league=league,
            defaults={"team": team},
        )
        messages.success(self.request, "Тренер назначен.")
        return super().form_valid(form)


class ManagerLeagueTeamsView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER",)

    def get(self, request, league_pk):
        league = get_object_or_404(League, pk=league_pk, manager=request.user)
        teams = (
            league.teams.order_by("name")
            .values("id", "name")
        )
        return JsonResponse({"teams": list(teams)})


class CoachTeamRosterView(RoleRequiredMixin, TemplateView):
    allowed_roles = ("COACH",)
    template_name = "leagues/coach_team_roster.html"

    def get_team(self):
        team = get_object_or_404(Team, pk=self.kwargs["team_pk"])
        if team.captain_id != self.request.user.id:
            raise PermissionDenied()
        return team

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        team = self.get_team()
        ctx["team"] = team
        leagues = team.leagues.order_by("-season", "sport")
        ctx["leagues"] = leagues
        selected_league_id = self.request.GET.get("league") or self.request.POST.get("league")
        league = leagues.filter(pk=selected_league_id).first() if selected_league_id else leagues.first()
        ctx["league"] = league
        if league:
            in_league_ids = (
                User.objects.filter(teams__leagues=league)
                .values_list("pk", flat=True)
                .distinct()
            )
            ctx["free_players"] = (
                User.objects.filter(profile__role=UserProfile.Role.PLAYER)
                .filter(profile__faculty=team.faculty)
                .filter(profile__course=team.course) if team.course else User.objects.filter(profile__role=UserProfile.Role.PLAYER).filter(profile__faculty=team.faculty)
            )
            ctx["free_players"] = (
                ctx["free_players"]
                .exclude(pk__in=in_league_ids)
                .select_related("profile")
                .order_by("username")
            )
        else:
            ctx["free_players"] = User.objects.none()
        ctx["main_squad"] = team.players.exclude(pk__in=team.reserve_players.values_list("pk", flat=True)).select_related("profile")
        ctx["reserve_squad"] = team.reserve_players.all().select_related("profile")
        return ctx

    def post(self, request, team_pk):
        team = self.get_team()
        leagues = team.leagues.all()
        selected_league_id = request.POST.get("league")
        league = leagues.filter(pk=selected_league_id).first() if selected_league_id else leagues.first()
        if request.POST.get("add_player"):
            pid = request.POST.get("player_id")
            player = get_object_or_404(User, pk=pid, profile__role=UserProfile.Role.PLAYER)
            if league and _user_in_league(player, league):
                messages.error(request, "Игрок уже в команде этой лиги.")
            elif team.players.filter(pk=player.pk).exists():
                messages.info(request, "Игрок уже в составе команды.")
            else:
                team.players.add(player)
                CoachRosterAction.objects.create(
                    coach=request.user,
                    team=team,
                    player=player,
                    action=CoachRosterAction.Action.ADD,
                )
                if league:
                    TeamJoinRequest.objects.filter(user=player, league=league).delete()
                messages.success(request, "Игрок добавлен.")
        elif request.POST.get("toggle_reserve"):
            pid = request.POST.get("player_id")
            player = get_object_or_404(User, pk=pid)
            if not team.players.filter(pk=player.pk).exists():
                messages.error(request, "Игрок не в составе команды.")
            elif player == team.captain:
                messages.error(request, "Тренера нельзя переводить в запас.")
            else:
                if team.reserve_players.filter(pk=player.pk).exists():
                    team.reserve_players.remove(player)
                    messages.success(request, "Игрок переведён в основной состав.")
                else:
                    team.reserve_players.add(player)
                    messages.success(request, "Игрок переведён в запас.")
        elif request.POST.get("remove_player"):
            pid = request.POST.get("player_id")
            player = get_object_or_404(User, pk=pid)
            if player == team.captain:
                messages.error(request, "Нельзя удалить тренера из состава.")
            else:
                team.players.remove(player)
                team.reserve_players.remove(player)
                CoachRosterAction.objects.create(
                    coach=request.user,
                    team=team,
                    player=player,
                    action=CoachRosterAction.Action.REMOVE,
                )
                if league:
                    TeamJoinRequest.objects.filter(user=player, league=league).delete()
                messages.success(request, "Игрок исключён из команды.")
        url = reverse("leagues:coach_team_roster", args=[team.pk])
        if league:
            return redirect(f"{url}?league={league.pk}")
        return redirect(url)


class CoachMessagePlayersView(RoleRequiredMixin, View):
    allowed_roles = ("COACH",)

    def post(self, request, team_pk):
        team = get_object_or_404(Team, pk=team_pk, captain=request.user)
        text = (request.POST.get("message") or "").strip()
        if not text:
            messages.error(request, "Введите текст сообщения для игроков.")
            return redirect("leagues:role_coach")
        for p in team.players.all():
            _notify(
                p,
                f"Сообщение от тренера команды «{team.name}»: {text[:250]}",
                reverse("leagues:team_detail", args=[team.pk]),
            )
        messages.success(request, "Сообщение отправлено игрокам команды.")
        return redirect("leagues:role_coach")


class CoachBioUpdateView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN", "MANAGER", "COACH")

    def post(self, request, pk):
        coach = get_object_or_404(User, pk=pk)
        profile, _ = UserProfile.objects.get_or_create(user=coach)
        role = _resolve_user_role(request.user)
        if role == "COACH" and request.user.id != coach.id:
            raise PermissionDenied()
        if role == "MANAGER":
            # Менеджер может редактировать описание только тренерам, связанным с его лигами
            managed_leagues = League.objects.filter(manager=request.user)
            is_related = CoachAssignment.objects.filter(
                user=coach, league__in=managed_leagues
            ).exists() or Team.objects.filter(
                captain=coach, leagues__in=managed_leagues
            ).exists()
            if not is_related:
                raise PermissionDenied()
        profile.bio = (request.POST.get("bio") or "").strip()
        profile.save(update_fields=["bio"])
        messages.success(request, "Описание тренера обновлено.")
        return redirect("leagues:coach_detail", pk=pk)


# ─── coach actions ─────────────────────────────────────────────────

class ConfirmParticipationView(RoleRequiredMixin, View):
    allowed_roles = ("COACH",)

    def post(self, request, pk):
        participation = get_object_or_404(MatchParticipation, pk=pk)
        if participation.team.captain != request.user:
            messages.error(request, "Вы не тренер этой команды.")
            return redirect("leagues:home")
        participation.confirmed = True
        participation.confirmed_by = request.user
        participation.confirmed_at = timezone.now()
        participation.save()
        messages.success(request, "Участие подтверждено.")
        return redirect("leagues:match_detail", pk=participation.match.pk)


class ManageAttendanceView(RoleRequiredMixin, TemplateView):
    allowed_roles = ("COACH",)
    template_name = "leagues/manage_attendance.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        match = get_object_or_404(Match, pk=self.kwargs["match_pk"])
        team = get_object_or_404(Team, pk=self.kwargs["team_pk"])
        ctx["match"] = match
        ctx["team"] = team
        players = team.players.all()
        attendance_map = {a.player_id: a for a in match.attendances.filter(team=team)}
        items = []
        for p in players:
            att = attendance_map.get(p.pk)
            items.append({
                "player": p,
                "status": att.status if att else PlayerAttendance.Reason.PRESENT,
            })
        ctx["items"] = items
        ctx["reason_choices"] = PlayerAttendance.Reason.choices
        return ctx

    def post(self, request, match_pk, team_pk):
        match = get_object_or_404(Match, pk=match_pk)
        team = get_object_or_404(Team, pk=team_pk)
        if team.captain != request.user:
            messages.error(request, "Вы не тренер этой команды.")
            return redirect("leagues:home")
        for player in team.players.all():
            status = request.POST.get(f"status_{player.pk}", PlayerAttendance.Reason.PRESENT)
            PlayerAttendance.objects.update_or_create(
                match=match, player=player,
                defaults={"team": team, "status": status},
            )
        messages.success(request, "Состав обновлён.")
        return redirect("leagues:match_detail", pk=match_pk)


# ─── announcements ─────────────────────────────────────────────────

class AnnouncementCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ("MANAGER", "ADMIN")
    model = Announcement
    form_class = AnnouncementForm
    template_name = "leagues/announcement_form.html"

    def dispatch(self, request, *args, **kwargs):
        if _resolve_user_role(request.user) == "MANAGER" and not _manager_has_leagues(request.user):
            messages.error(request, "У вас нет назначенной лиги.")
            return redirect("leagues:role_manager")
        return super().dispatch(request, *args, **kwargs)

    def _locked_league(self):
        league_id = self.request.GET.get("league") or self.request.POST.get("league")
        if not league_id:
            return None
        return _leagues_for_match_or_announcement(self.request.user).filter(pk=league_id).first()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        locked_league = self._locked_league()
        if locked_league:
            kwargs["league_queryset"] = League.objects.filter(pk=locked_league.pk)
        else:
            kwargs["league_queryset"] = _leagues_for_match_or_announcement(self.request.user)
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        locked_league = self._locked_league()
        if locked_league:
            initial["league"] = locked_league.pk
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["locked_league"] = self._locked_league()
        return ctx

    def form_valid(self, form):
        form.instance.author = self.request.user
        response = super().form_valid(form)
        # notify all players in teams of this league
        league = self.object.league
        teams = league.teams.all()
        users = User.objects.filter(teams__in=teams).distinct()
        for u in users:
            _notify(u, f"Новое объявление в {league}: {self.object.title}",
                    reverse("leagues:league_detail", args=[league.pk]))
        messages.success(self.request, "Объявление опубликовано.")
        return response

    def get_success_url(self):
        return reverse("leagues:league_detail", args=[self.object.league.pk])


# ─── notifications ─────────────────────────────────────────────────

class NotificationListView(LoginRequiredMixin, ListView):
    template_name = "leagues/notifications.html"
    context_object_name = "notifications"
    paginate_by = 30

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class MarkNotificationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        n = get_object_or_404(Notification, pk=pk, user=request.user)
        n.is_read = True
        n.save()
        if n.link:
            return redirect(n.link)
        return redirect("leagues:notifications")


# ─── profile ───────────────────────────────────────────────────────

class ProfileView(LoginRequiredMixin, TemplateView):
    template_name = "leagues/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)
        ctx["profile"] = profile
        ctx["faculty_label"] = (
            dict(Team.Faculty.choices).get(profile.faculty, profile.faculty)
            if profile.faculty
            else "—"
        )
        ctx["study_group_display"] = profile.study_group or "—"
        ctx["form"] = ProfileForm(
            initial={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "faculty": profile.faculty,
                "study_group": profile.study_group,
                "course": profile.course,
                "age": profile.age,
                "bio": profile.bio,
            },
        )
        ctx["profile_photo"] = profile.photo
        ctx["my_teams"] = Team.objects.filter(Q(players=user) | Q(captain=user)).distinct()
        return ctx

    def post(self, request):
        form = ProfileForm(request.POST, request.FILES)
        if form.is_valid():
            request.user.first_name = form.cleaned_data.get("first_name", "")
            request.user.last_name = form.cleaned_data.get("last_name", "")
            request.user.email = form.cleaned_data.get("email", "")
            request.user.save()
            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            profile.faculty = form.cleaned_data.get("faculty") or profile.faculty
            profile.study_group = (form.cleaned_data.get("study_group") or "").strip()
            profile.course = form.cleaned_data.get("course") or profile.course
            profile.age = form.cleaned_data.get("age")
            profile.bio = (form.cleaned_data.get("bio") or "").strip()
            if form.cleaned_data.get("photo"):
                profile.photo = form.cleaned_data["photo"]
            profile.save()
            messages.success(request, "Профиль обновлён.")
        return redirect("leagues:profile")


# ─── role dashboards ───────────────────────────────────────────────

class AdminDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_admin.html"
    allowed_roles = ("ADMIN",)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["total_teams"] = Team.objects.count()
        ctx["total_leagues"] = League.objects.count()
        ctx["total_matches"] = Match.objects.count()
        ctx["total_users"] = User.objects.count()
        ctx["recent_matches"] = Match.objects.filter(status=Match.Status.COMPLETED).order_by("-date_time")[:5]
        ctx["leagues"] = League.objects.all()
        ctx["teams"] = Team.objects.all()
        return ctx


class ManagerDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_manager.html"
    allowed_roles = ("MANAGER",)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        my_leagues = League.objects.filter(manager=self.request.user).order_by("-season", "sport")
        ctx["my_leagues"] = my_leagues
        ctx["primary_league"] = my_leagues.first()
        ctx["upcoming_matches"] = (
            Match.objects.filter(
                league__manager=self.request.user,
                date_time__gte=timezone.now(),
            )
            .select_related("home_team", "away_team")
            .order_by("date_time")[:10]
        )
        ctx["manager_match_grid"] = (
            Match.objects.filter(league__manager=self.request.user)
            .select_related("home_team", "away_team", "league")
            .order_by("date_time")[:50]
        )
        return ctx


class CoachDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_coach.html"
    allowed_roles = ("COACH",)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        teams = Team.objects.filter(captain=self.request.user).prefetch_related("players")
        ctx["coach_teams"] = teams
        ctx["team_matches"] = (
            Match.objects.filter(
                Q(home_team__in=teams) | Q(away_team__in=teams),
                date_time__gte=timezone.now(),
            )
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        # pending confirmations
        ctx["pending_confirmations"] = MatchParticipation.objects.filter(
            team__in=teams, confirmed=False,
            match__date_time__gte=timezone.now(),
        ).select_related("match", "team", "match__home_team", "match__away_team")
        completed = Match.objects.filter(
            Q(home_team__in=teams) | Q(away_team__in=teams),
            status=Match.Status.COMPLETED,
        )
        wins = completed.filter(
            Q(home_team__in=teams, score_home__gt=F("score_away")) |
            Q(away_team__in=teams, score_away__gt=F("score_home"))
        ).count()
        ctx["coach_stats"] = {
            "played": completed.count(),
            "wins": wins,
            "losses": completed.count() - wins,
            "added_players": CoachRosterAction.objects.filter(
                coach=self.request.user, action=CoachRosterAction.Action.ADD
            ).count(),
            "removed_players": CoachRosterAction.objects.filter(
                coach=self.request.user, action=CoachRosterAction.Action.REMOVE
            ).count(),
        }
        ctx["coach_team_players"] = {
            t.pk: t.players.all() for t in teams
        }
        return ctx


class PlayerDashboardView(RoleRequiredMixin, TemplateView):
    template_name = "leagues/role_player.html"
    allowed_roles = ("PLAYER",)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.now()
        teams = Team.objects.filter(players=self.request.user)
        ctx["my_teams"] = teams
        ctx["my_matches"] = (
            Match.objects.filter(
                Q(home_team__in=teams) | Q(away_team__in=teams),
                date_time__gte=timezone.now(),
            )
            .select_related("home_team", "away_team")
            .order_by("date_time")
        )
        ctx["recent_results"] = (
            Match.objects.filter(
                Q(home_team__in=teams) | Q(away_team__in=teams),
                status=Match.Status.COMPLETED,
            )
            .select_related("home_team", "away_team")
            .order_by("-date_time")[:10]
        )
        ctx["votable_match_ids"] = {
            m.pk for m in ctx["recent_results"]
            if now <= ((m.completed_at or m.date_time) + timezone.timedelta(hours=24))
        }
        ctx["my_join_requests"] = (
            TeamJoinRequest.objects.filter(
                user=self.request.user,
                status=TeamJoinRequest.Status.PENDING,
            )
            .select_related("league", "team")
            .order_by("-created_at")
        )
        return ctx


class StubPasswordResetView(PasswordResetView):
    template_name = "registration/password_reset_form.html"
    email_template_name = "registration/password_reset_email.html"
    success_url = reverse_lazy("password_reset_done")

    def form_valid(self, form):
        response = super().form_valid(form)
        email = form.cleaned_data.get("email", "")
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            link = self.request.build_absolute_uri(
                reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
            )
            self.request.session["password_reset_stub_link"] = link
        else:
            self.request.session["password_reset_stub_link"] = ""
        return response


class StubPasswordResetDoneView(TemplateView):
    template_name = "registration/password_reset_done.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["password_reset_stub_link"] = self.request.session.get("password_reset_stub_link", "")
        return ctx


# ─── export ────────────────────────────────────────────────────────

class ExportMatchesCSVView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER", "ADMIN")

    def get(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="matches.csv"'
        response.write("\ufeff")  # BOM for Excel
        writer = csv.writer(response)
        writer.writerow(["ID", "Лига", "Хозяева", "Гости", "Дата", "Место", "Счёт", "Статус"])
        qs = Match.objects.select_related("home_team", "away_team", "league").order_by("date_time")
        if _resolve_user_role(request.user) == "MANAGER":
            qs = qs.filter(league__manager=request.user)
        for m in qs:
            score = f"{m.score_home}:{m.score_away}" if m.score_home is not None else "—"
            writer.writerow([
                m.pk,
                str(m.league) if m.league else "—",
                m.home_team.name,
                m.away_team.name,
                m.date_time.strftime("%d.%m.%Y %H:%M"),
                m.location,
                score,
                m.get_status_display(),
            ])
        return response


class ExportTeamsCSVView(RoleRequiredMixin, View):
    allowed_roles = ("MANAGER", "ADMIN")

    def get(self, request):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="teams.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["ID", "Команда", "Факультет", "Капитан", "Игроков"])
        for t in Team.objects.select_related("captain").annotate(player_count=Count("players")):
            writer.writerow([
                t.pk,
                t.name,
                t.get_faculty_display(),
                t.captain.username if t.captain else "—",
                t.player_count,
            ])
        return response


# ─── admin: manage leagues/teams ───────────────────────────────────

class LeagueCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ("ADMIN",)
    model = League
    form_class = LeagueForm
    template_name = "leagues/league_form.html"

    def get_success_url(self):
        return reverse("leagues:league_detail", args=[self.object.pk])


class LeagueUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ("ADMIN",)
    model = League
    form_class = LeagueForm
    template_name = "leagues/league_form.html"

    def get_success_url(self):
        return reverse("leagues:league_detail", args=[self.object.pk])


class LeagueDeleteView(RoleRequiredMixin, DeleteView):
    allowed_roles = ("ADMIN",)
    model = League
    template_name = "leagues/confirm_delete.html"
    success_url = reverse_lazy("leagues:league_list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["entity_name"] = f"лигу «{self.object}»"
        return ctx


class MatchUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ("ADMIN",)
    model = Match
    form_class = MatchCreateForm
    template_name = "leagues/match_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["league_queryset"] = League.objects.all().order_by("-season", "sport")
        return kwargs

    def get_success_url(self):
        return reverse("leagues:match_detail", args=[self.object.pk])


class MatchDeleteView(RoleRequiredMixin, DeleteView):
    allowed_roles = ("ADMIN",)
    model = Match
    template_name = "leagues/confirm_delete.html"
    success_url = reverse_lazy("leagues:match_list_all")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["entity_name"] = f"матч «{self.object}»"
        return ctx


class LeagueStatusUpdateView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN", "MANAGER")

    def post(self, request, pk):
        league = get_object_or_404(League, pk=pk)
        if _resolve_user_role(request.user) == "MANAGER" and league.manager_id != request.user.id:
            raise PermissionDenied()
        status = request.POST.get("status")
        if status not in dict(League.Status.choices):
            messages.error(request, "Некорректный статус.")
            return redirect("leagues:league_detail", pk=pk)
        league.status = status
        league.save(update_fields=["status"])
        messages.success(request, "Статус лиги обновлён.")
        return redirect("leagues:league_detail", pk=pk)


class AdminUserCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = ("ADMIN",)
    template_name = "leagues/admin_user_form.html"
    form_class = AdminUserCreateForm
    success_url = reverse_lazy("leagues:admin_users")

    def form_valid(self, form):
        response = super().form_valid(form)
        role = form.cleaned_data["role"]
        UserProfile.objects.update_or_create(user=self.object, defaults={"role": role})
        messages.success(self.request, "Пользователь создан.")
        return response


class AdminUserUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = ("ADMIN",)
    model = User
    template_name = "leagues/admin_user_form.html"
    form_class = AdminUserUpdateForm
    success_url = reverse_lazy("leagues:admin_users")

    def get_initial(self):
        initial = super().get_initial()
        profile, _ = UserProfile.objects.get_or_create(user=self.object)
        initial["role"] = profile.role
        return initial

    def form_valid(self, form):
        response = super().form_valid(form)
        role = form.cleaned_data["role"]
        UserProfile.objects.update_or_create(user=self.object, defaults={"role": role})
        messages.success(self.request, "Пользователь обновлён.")
        return response


class AdminUserDeleteView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN",)

    def post(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        if user.id == request.user.id:
            messages.error(request, "Нельзя удалить самого себя.")
            return redirect("leagues:admin_users")
        user.delete()
        messages.success(request, "Пользователь удалён.")
        return redirect("leagues:admin_users")


class AdminTeamManageView(RoleRequiredMixin, ListView):
    allowed_roles = ("ADMIN",)
    template_name = "leagues/admin_team_manage.html"
    context_object_name = "teams"
    paginate_by = 40

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["assignable_users"] = User.objects.filter(is_active=True).order_by("username")
        return ctx

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        qs = Team.objects.select_related("captain").annotate(player_count=Count("players")).order_by("name")
        if q:
            qs = qs.filter(name__icontains=q)
        return qs

    def post(self, request, *args, **kwargs):
        rename_team_id = request.POST.get("rename_team_id")
        if rename_team_id:
            team = get_object_or_404(Team, pk=rename_team_id)
            new_name = (request.POST.get("new_team_name") or "").strip()
            if not new_name:
                messages.error(request, "Введите новое название команды.")
                return redirect("leagues:admin_teams")
            if Team.objects.exclude(pk=team.pk).filter(name__iexact=new_name).exists():
                messages.error(request, "Команда с таким названием уже существует.")
                return redirect("leagues:admin_teams")
            team.name = new_name
            team.save(update_fields=["name"])
            messages.success(request, "Название команды обновлено.")
            return redirect("leagues:admin_teams")
        assign_team = request.POST.get("assign_coach_team")
        if assign_team:
            team = get_object_or_404(Team, pk=assign_team)
            coach_id = request.POST.get("coach_user_id")
            if not coach_id:
                messages.error(request, "Выберите пользователя-тренера.")
            else:
                coach = get_object_or_404(User, pk=coach_id)
                team.captain = coach
                team.save(update_fields=["captain"])
                profile, _ = UserProfile.objects.get_or_create(user=coach)
                if profile.role == UserProfile.Role.PLAYER:
                    profile.role = UserProfile.Role.COACH
                    profile.save(update_fields=["role"])
                messages.success(request, f"Тренер для «{team.name}» назначен.")
            return redirect("leagues:admin_teams")
        team_id = request.POST.get("delete_team_id")
        if team_id:
            team = get_object_or_404(Team, pk=team_id)
            team.delete()
            messages.success(request, "Команда удалена.")
        return redirect("leagues:admin_teams")


class AdminAuditLogView(RoleRequiredMixin, ListView):
    allowed_roles = ("ADMIN",)
    template_name = "leagues/admin_audit_logs.html"
    context_object_name = "logs"
    paginate_by = 100

    def get_queryset(self):
        qs = AuditLog.objects.select_related("user")
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(path__icontains=q) | Q(user__username__icontains=q) | Q(method__icontains=q)
            )
        return qs


class AdminAnalyticsReportView(RoleRequiredMixin, TemplateView):
    allowed_roles = ("ADMIN",)
    template_name = "leagues/admin_analytics.html"

    def _faculty_data(self):
        team_counts = Team.objects.values("faculty").annotate(teams=Count("id"))
        player_counts = (
            UserProfile.objects.filter(role=UserProfile.Role.PLAYER)
            .values("faculty")
            .annotate(players=Count("id"))
        )
        team_map = {i["faculty"]: i["teams"] for i in team_counts}
        player_map = {i["faculty"]: i["players"] for i in player_counts}
        rows = []
        for code, label in Team.Faculty.choices:
            rows.append(
                {
                    "faculty_code": code,
                    "faculty_label": label,
                    "teams": team_map.get(code, 0),
                    "players": player_map.get(code, 0),
                }
            )
        return rows

    def _match_stats_data(self):
        rows = []
        for code, label in League.Sport.choices:
            total = Match.objects.filter(league__sport=code, status=Match.Status.COMPLETED).count()
            rows.append({"sport_code": code, "sport_label": label, "matches": total})
        return rows

    def _render_pdf(self, title, headers, rows):
        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="analytics.pdf"'
        c = canvas.Canvas(response, pagesize=A4)
        w, h = A4
        y = h - 50
        font_name = "Helvetica"
        try:
            candidates = [
                r"C:\Windows\Fonts\arial.ttf",
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeui.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
            font_path = next((p for p in candidates if os.path.exists(p)), None)
            if font_path:
                font_name = "UniSportUnicode"
                if font_name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(font_name, font_path))
        except Exception:
            font_name = "Helvetica"

        c.setFont(font_name, 14)
        c.drawString(40, y, title)
        y -= 28
        c.setFont(font_name, 10)
        c.drawString(40, y, " | ".join(headers))
        y -= 18
        c.setFont(font_name, 10)
        for row in rows:
            line = " | ".join(str(x) for x in row)
            c.drawString(40, y, line[:150])
            y -= 16
            if y < 50:
                c.showPage()
                y = h - 50
                c.setFont(font_name, 10)
        c.showPage()
        c.save()
        return response

    def _render_csv(self, filename, headers, rows):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return response

    def get(self, request, *args, **kwargs):
        report_type = request.GET.get("type")
        fmt = request.GET.get("format")
        if report_type in {"faculty", "matches"} and fmt in {"csv", "pdf"}:
            if report_type == "faculty":
                data = self._faculty_data()
                headers = ["Факультет", "Команд", "Игроков"]
                rows = [[d["faculty_label"], d["teams"], d["players"]] for d in data]
                title = "Отчёт: активность по факультетам"
                if fmt == "csv":
                    return self._render_csv("faculty_activity.csv", headers, rows)
                return self._render_pdf(title, headers, rows)
            data = self._match_stats_data()
            headers = ["Вид спорта", "Проведено матчей"]
            rows = [[d["sport_label"], d["matches"]] for d in data]
            title = "Отчёт: статистика матчей"
            if fmt == "csv":
                return self._render_csv("match_stats.csv", headers, rows)
            return self._render_pdf(title, headers, rows)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["faculty_report"] = self._faculty_data()
        ctx["match_report"] = self._match_stats_data()
        return ctx


class AdminImportCSVView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN",)

    def post(self, request):
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Выберите CSV файл.")
            return redirect("leagues:admin_analytics")
        try:
            text = csv_file.read().decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            created = 0
            for row in reader:
                name = (row.get("name") or "").strip()
                faculty = (row.get("faculty") or "").strip().upper()
                if not name or faculty not in {c[0] for c in Team.Faculty.choices}:
                    continue
                team, is_new = Team.objects.get_or_create(
                    name=name, defaults={"faculty": faculty}
                )
                if not is_new and team.faculty != faculty:
                    team.faculty = faculty
                    team.save(update_fields=["faculty"])
                league_id = (row.get("league_id") or "").strip()
                if league_id:
                    league = League.objects.filter(pk=league_id).first()
                    if league:
                        team.leagues.add(league)
                if is_new:
                    created += 1
            messages.success(request, f"Импорт завершён. Создано команд: {created}.")
        except Exception as exc:
            messages.error(request, f"Ошибка импорта CSV: {exc}")
        return redirect("leagues:admin_analytics")


class AdminBackupDatabaseView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN",)

    def get(self, request):
        response = HttpResponse(content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="unisport_backup.json"'
        call_command("dumpdata", stdout=response, indent=2)
        return response


class AdminRestoreDatabaseView(RoleRequiredMixin, View):
    allowed_roles = ("ADMIN",)

    def post(self, request):
        backup_file = request.FILES.get("backup_file")
        if not backup_file:
            messages.error(request, "Выберите backup JSON.")
            return redirect("leagues:admin_analytics")
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp:
                for chunk in backup_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name
            call_command("loaddata", tmp_path)
            messages.success(request, "Восстановление из backup успешно завершено.")
        except Exception as exc:
            messages.error(request, f"Ошибка восстановления: {exc}")
        return redirect("leagues:admin_analytics")


# ─── REST API ──────────────────────────────────────────────────────

class MatchSerializer(serializers.ModelSerializer):
    home_team = serializers.CharField(source="home_team.name")
    away_team = serializers.CharField(source="away_team.name")
    league = serializers.CharField(source="league.__str__", default="")

    class Meta:
        model = Match
        fields = (
            "id", "league", "home_team", "away_team",
            "date_time", "location", "score_home", "score_away", "status",
        )


class MatchListApiView(generics.ListAPIView):
    queryset = Match.objects.select_related("home_team", "away_team", "league").order_by("date_time")
    serializer_class = MatchSerializer


class LeagueSerializer(serializers.ModelSerializer):
    manager = serializers.CharField(source="manager.username")
    sport_display = serializers.CharField(source="get_sport_display")

    class Meta:
        model = League
        fields = ("id", "sport", "sport_display", "season", "status", "manager")


class LeagueListApiView(generics.ListAPIView):
    queryset = League.objects.select_related("manager").order_by("-season")
    serializer_class = LeagueSerializer


