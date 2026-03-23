from django.contrib import admin
from .models import League, Match, Team, UserProfile


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "faculty", "captain", "created_at")
    search_fields = ("name", "faculty", "captain__username")
    list_filter = ("faculty", "created_at")
    filter_horizontal = ("players",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = (
        "home_team",
        "away_team",
        "date_time",
        "location",
        "score_home",
        "score_away",
        "status",
    )
    search_fields = ("home_team__name", "away_team__name", "location")
    list_filter = ("status", "date_time")


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ("sport", "season", "status", "manager")
    search_fields = ("sport", "season", "manager__username")
    list_filter = ("sport", "status", "season")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    search_fields = ("user__username", "user__email")
    list_filter = ("role",)
