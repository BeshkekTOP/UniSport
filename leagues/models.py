from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class UserProfile(models.Model):
    class Role(models.TextChoices):
        MANAGER = "MANAGER", "Менеджер"
        COACH = "COACH", "Тренер"
        PLAYER = "PLAYER", "Игрок"
    class Course(models.TextChoices):
        C1 = "1", "1 курс"
        C2 = "2", "2 курс"
        C3 = "3", "3 курс"
        C4 = "4", "4 курс"
        C5 = "5", "5 курс"
        C6 = "6", "6 курс"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PLAYER)
    faculty = models.CharField(max_length=10, blank=True, default="", verbose_name="факультет")
    study_group = models.CharField(max_length=64, blank=True, default="", verbose_name="группа")
    course = models.CharField(max_length=2, choices=Course.choices, blank=True, default="", verbose_name="курс")
    age = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="возраст")
    bio = models.TextField(blank=True, default="", verbose_name="описание")
    photo = models.FileField(upload_to="profile_photos/", blank=True, default="")

    def __str__(self) -> str:
        return f"{self.user.username} - {self.get_role_display()}"


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
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    manager = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="managed_leagues",
    )
    teams = models.ManyToManyField("Team", blank=True, related_name="leagues")

    class Meta:
        ordering = ["-season", "sport"]

    def __str__(self) -> str:
        return f"{self.get_sport_display()} ({self.season})"


class Team(models.Model):
    class Faculty(models.TextChoices):
        ECON = "ECON", "Экономический"
        BUS = "BUS", "Бизнес"
        ENG = "ENG", "Инженерный"
        IT = "IT", "Информационные технологии"
        LAW = "LAW", "Юридический"

    name = models.CharField(max_length=100, unique=True)
    faculty = models.CharField(max_length=10, choices=Faculty.choices)
    course = models.CharField(
        max_length=2,
        choices=UserProfile.Course.choices,
        blank=True,
        default="",
        verbose_name="курс",
    )
    captain = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="captained_teams",
        verbose_name="тренер",
    )
    players = models.ManyToManyField(User, blank=True, related_name="teams")
    reserve_players = models.ManyToManyField(
        User,
        blank=True,
        related_name="reserve_teams",
        verbose_name="запас",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Match(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Запланирован"
        IN_PROGRESS = "IN_PROGRESS", "В процессе"
        COMPLETED = "COMPLETED", "Завершен"

    league = models.ForeignKey(
        League,
        on_delete=models.CASCADE,
        related_name="matches",
        null=True,
        blank=True,
    )
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
    completed_at = models.DateTimeField(null=True, blank=True)

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


class MatchParticipation(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="participations")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    confirmed = models.BooleanField(default=False)
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("match", "team")

    def __str__(self) -> str:
        status = "Подтверждено" if self.confirmed else "Ожидает"
        return f"{self.team} — {self.match} ({status})"


class PlayerAttendance(models.Model):
    class Reason(models.TextChoices):
        PRESENT = "PRESENT", "Присутствует"
        ABSENT = "ABSENT", "Отсутствует"
        INJURY = "INJURY", "Травма"
        ACADEMIC = "ACADEMIC", "Учеба"

    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="attendances")
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="attendances")
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=Reason.choices, default=Reason.PRESENT)

    class Meta:
        unique_together = ("match", "player")

    def __str__(self) -> str:
        return f"{self.player.username} — {self.get_status_display()}"


class Announcement(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="announcements")
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    message = models.CharField(max_length=500)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    link = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{'✓' if self.is_read else '•'}] {self.message[:60]}"


class TeamJoinRequest(models.Model):
    """Заявка игрока в команду в рамках лиги (не более одной активной записи на лигу)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "На рассмотрении"
        APPROVED = "APPROVED", "Принята"
        REJECTED = "REJECTED", "Отклонена"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="team_join_requests")
    team = models.ForeignKey("Team", on_delete=models.CASCADE, related_name="join_requests")
    league = models.ForeignKey("League", on_delete=models.CASCADE, related_name="team_join_requests")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "league"], name="unique_join_request_user_league"),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.team} ({self.get_status_display()})"


class CoachAssignment(models.Model):
    """Назначение тренера менеджером лиги (дублирует связь с командой для учёта по лиге)."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="coach_assignments")
    league = models.ForeignKey("League", on_delete=models.CASCADE, related_name="coach_assignments")
    team = models.ForeignKey(
        "Team",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coach_assignments",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "league"], name="unique_coach_user_league"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.league}"


class GoalEvent(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="goal_events")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="goal_events")
    scorer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scored_goals")
    minute = models.PositiveSmallIntegerField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["minute", "created_at"]

    def __str__(self) -> str:
        return f"{self.scorer.username} {self.minute}' ({self.team.name})"


class MatchMVPVote(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="mvp_votes")
    voter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mvp_votes_made")
    candidate = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mvp_votes_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["match", "voter"], name="unique_mvp_vote_per_match_voter"),
        ]

    def __str__(self) -> str:
        return f"{self.voter.username} -> {self.candidate.username} ({self.match_id})"


class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=300)
    status_code = models.PositiveSmallIntegerField(default=200)
    ip = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        who = self.user.username if self.user else "anon"
        return f"{self.method} {self.path} ({self.status_code}) by {who}"


class CoachRosterAction(models.Model):
    class Action(models.TextChoices):
        ADD = "ADD", "Добавлен"
        REMOVE = "REMOVE", "Удален"

    coach = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roster_actions")
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="roster_actions")
    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roster_action_entries")
    action = models.CharField(max_length=10, choices=Action.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.coach} {self.get_action_display()} {self.player} ({self.team})"
