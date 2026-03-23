from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class UserProfile(models.Model):
    class Role(models.TextChoices):
        MANAGER = "MANAGER", "Менеджер"
        CAPTAIN = "CAPTAIN", "Капитан команды"
        PLAYER = "PLAYER", "Игрок"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PLAYER)

    def __str__(self) -> str:
        return f"{self.user.username} - {self.get_role_display()}"


class Team(models.Model):
    class Faculty(models.TextChoices):
        ECON = "ECON", "Экономический"
        BUS = "BUS", "Бизнес"
        ENG = "ENG", "Инженерный"
        IT = "IT", "Информационные технологии"
        LAW = "LAW", "Юридический"

    name = models.CharField(max_length=100, unique=True)
    faculty = models.CharField(max_length=10, choices=Faculty.choices)
    captain = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="captained_teams",
    )
    players = models.ManyToManyField(User, blank=True, related_name="teams")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class League(models.Model):
    class Sport(models.TextChoices):
        BASKETBALL = "BASKETBALL", "Баскетбол"
        FOOTBALL = "FOOTBALL", "Футбол"
        VOLLEYBALL = "VOLLEYBALL", "Волейбол"
        FUTSAL = "FUTSAL", "Мини-футбол"

    class Status(models.TextChoices):
        PLANNING = "PLANNING", "Планирование"
        ACTIVE = "ACTIVE", "Активна"
        FINISHED = "FINISHED", "Завершена"

    sport = models.CharField(max_length=20, choices=Sport.choices)
    season = models.CharField(max_length=20, default="2025/2026")
    status = models.CharField(max_length=20, choices=Status.choices)
    manager = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="managed_leagues",
    )

    class Meta:
        ordering = ["-season", "sport"]

    def __str__(self) -> str:
        return f"{self.get_sport_display()} ({self.season})"


class Match(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Запланирован"
        COMPLETED = "COMPLETED", "Завершен"

    home_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="home_matches",
    )
    away_team = models.ForeignKey(
        Team,
        on_delete=models.CASCADE,
        related_name="away_matches",
    )
    date_time = models.DateTimeField()
    location = models.CharField(max_length=200)
    score_home = models.PositiveIntegerField(null=True, blank=True)
    score_away = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    class Meta:
        ordering = ["date_time"]
        constraints = [
            models.CheckConstraint(
                check=~models.Q(home_team=models.F("away_team")),
                name="match_home_away_different",
            )
        ]

    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team} ({self.date_time:%Y-%m-%d %H:%M})"
