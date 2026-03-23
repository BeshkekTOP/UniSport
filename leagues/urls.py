from django.urls import path

from .views import (
    AdminDashboardView,
    CaptainDashboardView,
    HomePageView,
    LeagueListView,
    ManagerDashboardView,
    MatchListApiView,
    MatchScheduleView,
    PlayerDashboardView,
    RegisterView,
    TeamDetailView,
)

app_name = "leagues"

urlpatterns = [
    path("", HomePageView.as_view(), name="home"),
    path("register/", RegisterView.as_view(), name="register"),
    path("leagues/", LeagueListView.as_view(), name="league_list"),
    path("matches/schedule/", MatchScheduleView.as_view(), name="match_schedule"),
    path("teams/<int:pk>/", TeamDetailView.as_view(), name="team_detail"),
    path("roles/admin/", AdminDashboardView.as_view(), name="role_admin"),
    path("roles/manager/", ManagerDashboardView.as_view(), name="role_manager"),
    path("roles/captain/", CaptainDashboardView.as_view(), name="role_captain"),
    path("roles/player/", PlayerDashboardView.as_view(), name="role_player"),
    path("api/matches/", MatchListApiView.as_view(), name="api_match_list"),
]
