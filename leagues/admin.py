from django.contrib import admin
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


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty", "captain", "player_count", "created_at")
    search_fields = ("name", "faculty", "captain__username")
    list_filter = ("faculty", "created_at")
    filter_horizontal = ("players",)

    def player_count(self, obj):
        return obj.players.count()
    player_count.short_description = "Игроков"


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "home_team", "away_team", "league", "date_time",
        "location", "score_home", "score_away", "status",
    )
    search_fields = ("home_team__name", "away_team__name", "location")
    list_filter = ("status", "date_time", "league")


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("sport", "season", "status", "manager", "team_count")
    search_fields = ("sport", "season", "manager__username")
    list_filter = ("sport", "status", "season")
    filter_horizontal = ("teams",)

    def team_count(self, obj):
        return obj.teams.count()
    team_count.short_description = "Команд"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "faculty", "study_group")
    search_fields = ("user__username", "user__email")
    list_filter = ("role",)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "league", "author", "created_at")
    list_filter = ("league", "created_at")
    search_fields = ("title", "text")


@admin.register(MatchParticipation)
class MatchParticipationAdmin(admin.ModelAdmin):
    list_display = ("match", "team", "confirmed", "confirmed_by", "confirmed_at")
    list_filter = ("confirmed",)


@admin.register(PlayerAttendance)
class PlayerAttendanceAdmin(admin.ModelAdmin):
    list_display = ("match", "player", "team", "status")
    list_filter = ("status",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("message",)


@admin.register(TeamJoinRequest)
class TeamJoinRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "league", "status", "created_at")
    list_filter = ("status", "league")


@admin.register(CoachAssignment)
class CoachAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "league", "team")


@admin.register(GoalEvent)
class GoalEventAdmin(admin.ModelAdmin):
    list_display = ("match", "team", "scorer", "minute", "created_by", "created_at")
    list_filter = ("match", "team")
    search_fields = ("scorer__username",)


@admin.register(MatchMVPVote)
class MatchMVPVoteAdmin(admin.ModelAdmin):
    list_display = ("match", "voter", "candidate", "created_at")
    list_filter = ("match",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "method", "path", "status_code", "ip")
    list_filter = ("method", "status_code", "created_at")
    search_fields = ("path", "user__username", "ip")


@admin.register(CoachRosterAction)
class CoachRosterActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "coach", "team", "player", "action")
    list_filter = ("action", "created_at")
    search_fields = ("coach__username", "player__username", "team__name")
