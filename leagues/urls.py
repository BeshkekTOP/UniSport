from django.urls import path
from django.views.generic import RedirectView

from .views import (
    AboutView,
    AdminDashboardView,
    AdminUserListView,
    AdminUserCreateView,
    AdminUserDeleteView,
    AdminUserRoleView,
    AdminUserUpdateView,
    AdminAnalyticsReportView,
    AdminAuditLogView,
    AdminBackupDatabaseView,
    AdminImportCSVView,
    AdminRestoreDatabaseView,
    AdminTeamManageView,
    AnnouncementCreateView,
    CoachDashboardView,
    CoachJoinRequestView,
    CoachMessagePlayersView,
    CoachTeamRosterView,
    CoachDetailView,
    CoachBioUpdateView,
    CoachListView,
    ConfirmParticipationView,
    ExportMatchesCSVView,
    ExportTeamsCSVView,
    HomePageView,
    LeagueCreateView,
    LeagueDeleteView,
    LeagueDetailView,
    LeagueUpdateView,
    LeagueStatusUpdateView,
    LeagueListApiView,
    LeagueListView,
    ManageAttendanceView,
    ManagerLeagueTeamsView,
    ManagerCoachAssignView,
    ManagerDashboardView,
    MarkNotificationReadView,
    MatchCreateView,
    MatchDetailView,
    MatchDeleteView,
    MatchGoalEventCreateView,
    MatchListAllView,
    MatchMVPVoteView,
    MatchListApiView,
    MatchResultView,
    MatchStatusUpdateView,
    MatchUpdateView,
    MatchScheduleView,
    NotificationListView,
    PlayerDashboardView,
    PlayerDetailView,
    PlayerListView,
    PlayerJoinRequestCancelView,
    ProfileView,
    RegisterView,
    SearchView,
    TeamApplyView,
    TeamBrowseListView,
    TeamCreateView,
    TeamDeleteView,
    TeamDetailView,
    TeamUpdateView,
)

app_name = "leagues"

urlpatterns = [
    # public
    path("", HomePageView.as_view(), name="home"),
    path("about/", AboutView.as_view(), name="about"),
    path("search/", SearchView.as_view(), name="search"),
    path("register/", RegisterView.as_view(), name="register"),

    # catalog
    path("players/", PlayerListView.as_view(), name="player_list"),
    path("players/<int:pk>/", PlayerDetailView.as_view(), name="player_detail"),
    path("coaches/", CoachListView.as_view(), name="coach_list"),
    path("coaches/<int:pk>/", CoachDetailView.as_view(), name="coach_detail"),
    path("coaches/<int:pk>/bio/", CoachBioUpdateView.as_view(), name="coach_bio_update"),

    # leagues
    path("leagues/", LeagueListView.as_view(), name="league_list"),
    path("leagues/create/", LeagueCreateView.as_view(), name="league_create"),
    path("leagues/<int:pk>/edit/", LeagueUpdateView.as_view(), name="league_edit"),
    path("leagues/<int:pk>/delete/", LeagueDeleteView.as_view(), name="league_delete"),
    path("leagues/<int:pk>/", LeagueDetailView.as_view(), name="league_detail"),
    path(
        "leagues/<int:league_pk>/apply/<int:team_pk>/",
        TeamApplyView.as_view(),
        name="team_apply",
    ),
    path(
        "join-requests/<int:pk>/cancel/",
        PlayerJoinRequestCancelView.as_view(),
        name="join_request_cancel",
    ),

    # matches
    path("matches/all/", MatchListAllView.as_view(), name="match_list_all"),
    path("matches/schedule/", MatchScheduleView.as_view(), name="match_schedule"),
    path("matches/create/", MatchCreateView.as_view(), name="match_create"),
    path("matches/<int:pk>/edit/", MatchUpdateView.as_view(), name="match_edit"),
    path("matches/<int:pk>/delete/", MatchDeleteView.as_view(), name="match_delete"),
    path("matches/<int:pk>/", MatchDetailView.as_view(), name="match_detail"),
    path("matches/<int:pk>/result/", MatchResultView.as_view(), name="match_result"),
    path("matches/<int:pk>/status/", MatchStatusUpdateView.as_view(), name="match_status"),
    path("matches/<int:pk>/goal/", MatchGoalEventCreateView.as_view(), name="match_goal_create"),
    path("matches/<int:pk>/vote-mvp/", MatchMVPVoteView.as_view(), name="match_vote_mvp"),

    # teams
    path("teams/", TeamBrowseListView.as_view(), name="team_browse"),
    path("teams/create/", TeamCreateView.as_view(), name="team_create"),
    path("teams/<int:pk>/edit/", TeamUpdateView.as_view(), name="team_edit"),
    path("teams/<int:pk>/delete/", TeamDeleteView.as_view(), name="team_delete"),
    path(
        "teams/<int:team_pk>/roster/",
        CoachTeamRosterView.as_view(),
        name="coach_team_roster",
    ),
    path("teams/<int:team_pk>/message/", CoachMessagePlayersView.as_view(), name="coach_team_message"),
    path("teams/<int:pk>/", TeamDetailView.as_view(), name="team_detail"),

    # coach actions
    path(
        "join-requests/<int:pk>/decide/",
        CoachJoinRequestView.as_view(),
        name="join_request_decide",
    ),
    path("participation/<int:pk>/confirm/", ConfirmParticipationView.as_view(), name="confirm_participation"),
    path("matches/<int:match_pk>/teams/<int:team_pk>/attendance/", ManageAttendanceView.as_view(), name="manage_attendance"),

    # announcements
    path("announcements/create/", AnnouncementCreateView.as_view(), name="announcement_create"),

    # notifications
    path("notifications/", NotificationListView.as_view(), name="notifications"),
    path("notifications/<int:pk>/read/", MarkNotificationReadView.as_view(), name="notification_read"),

    # profile
    path("profile/", ProfileView.as_view(), name="profile"),

    # staff (admin UI — не /admin/, чтобы не конфликтовать с Django Admin)
    path("staff/users/", AdminUserListView.as_view(), name="admin_users"),
    path("staff/users/create/", AdminUserCreateView.as_view(), name="admin_user_create"),
    path("staff/users/<int:pk>/edit/", AdminUserUpdateView.as_view(), name="admin_user_edit"),
    path("staff/users/<int:pk>/role/", AdminUserRoleView.as_view(), name="admin_user_role"),
    path("staff/users/<int:pk>/delete/", AdminUserDeleteView.as_view(), name="admin_user_delete"),
    path("staff/teams/", AdminTeamManageView.as_view(), name="admin_teams"),
    path("staff/logs/", AdminAuditLogView.as_view(), name="admin_logs"),
    path("staff/analytics/", AdminAnalyticsReportView.as_view(), name="admin_analytics"),
    path("staff/import-csv/", AdminImportCSVView.as_view(), name="admin_import_csv"),
    path("staff/backup/", AdminBackupDatabaseView.as_view(), name="admin_backup"),
    path("staff/restore/", AdminRestoreDatabaseView.as_view(), name="admin_restore"),

    # league status
    path("leagues/<int:pk>/status/", LeagueStatusUpdateView.as_view(), name="league_status"),

    # manager: тренеры
    path("manage/coaches/", ManagerCoachAssignView.as_view(), name="manager_coach_assign"),
    path(
        "manage/leagues/<int:league_pk>/teams/",
        ManagerLeagueTeamsView.as_view(),
        name="manager_league_teams",
    ),

    # dashboards
    path("roles/admin/", AdminDashboardView.as_view(), name="role_admin"),
    path("roles/manager/", ManagerDashboardView.as_view(), name="role_manager"),
    path("roles/coach/", CoachDashboardView.as_view(), name="role_coach"),
    path(
        "roles/captain/",
        RedirectView.as_view(pattern_name="leagues:role_coach", permanent=False),
    ),
    path("roles/player/", PlayerDashboardView.as_view(), name="role_player"),

    # export
    path("export/matches/", ExportMatchesCSVView.as_view(), name="export_matches"),
    path("export/teams/", ExportTeamsCSVView.as_view(), name="export_teams"),

    # API
    path("api/matches/", MatchListApiView.as_view(), name="api_match_list"),
    path("api/leagues/", LeagueListApiView.as_view(), name="api_league_list"),
]
