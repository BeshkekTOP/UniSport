from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from .models import League, Match, Team, UserProfile, Notification, Announcement, MatchParticipation


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("testuser", "test@test.com", "pass123456")
        self.manager = User.objects.create_user("manager", "mgr@test.com", "pass123456")
        self.coach = User.objects.create_user("coach", "cap@test.com", "pass123456")
        UserProfile.objects.create(user=self.manager, role=UserProfile.Role.MANAGER)
        UserProfile.objects.create(user=self.coach, role=UserProfile.Role.COACH)

        self.team_a = Team.objects.create(name="Team A", faculty=Team.Faculty.IT, captain=self.coach)
        self.team_b = Team.objects.create(name="Team B", faculty=Team.Faculty.ECON)
        self.team_a.players.add(self.user, self.coach)

        self.league = League.objects.create(
            sport=League.Sport.BASKETBALL,
            season="2025/2026",
            status=League.Status.ACTIVE,
            manager=self.manager,
        )
        self.league.teams.add(self.team_a, self.team_b)

        self.match = Match.objects.create(
            league=self.league,
            home_team=self.team_a,
            away_team=self.team_b,
            date_time=timezone.now() + timezone.timedelta(days=1),
            location="Спортзал 1",
        )

    def test_user_profile_str(self):
        profile = UserProfile.objects.get(user=self.manager)
        self.assertIn("Менеджер", str(profile))

    def test_team_str(self):
        self.assertEqual(str(self.team_a), "Team A")

    def test_league_str(self):
        self.assertIn("Баскетбол", str(self.league))

    def test_match_str(self):
        self.assertIn("Team A", str(self.match))
        self.assertIn("Team B", str(self.match))

    def test_match_constraint(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Match.objects.create(
                home_team=self.team_a,
                away_team=self.team_a,
                date_time=timezone.now(),
                location="Test",
            )

    def test_notification_creation(self):
        n = Notification.objects.create(user=self.user, message="Test notification")
        self.assertFalse(n.is_read)

    def test_announcement_creation(self):
        a = Announcement.objects.create(
            league=self.league, author=self.manager,
            title="Test", text="Body",
        )
        self.assertEqual(str(a), "Test")

    def test_match_participation(self):
        p = MatchParticipation.objects.create(match=self.match, team=self.team_a)
        self.assertFalse(p.confirmed)


class ViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("player1", "p@t.com", "pass123456")
        UserProfile.objects.create(user=self.user, role=UserProfile.Role.PLAYER)

    def test_home_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)

    def test_about_page(self):
        r = self.client.get("/about/")
        self.assertEqual(r.status_code, 200)

    def test_league_list(self):
        r = self.client.get("/leagues/")
        self.assertEqual(r.status_code, 200)

    def test_match_schedule(self):
        r = self.client.get("/matches/schedule/")
        self.assertEqual(r.status_code, 200)

    def test_register_page(self):
        r = self.client.get("/register/")
        self.assertEqual(r.status_code, 200)

    def test_register_post(self):
        r = self.client.post("/register/", {
            "username": "newuser",
            "faculty": "IT",
            "study_group": "ИС-21",
            "course": "2",
            "age": 19,
            "email": "student@rea.ru",
            "password1": "StrongP@ss123",
            "password2": "StrongP@ss123",
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="newuser").exists())
        nu = User.objects.get(username="newuser")
        self.assertEqual(nu.profile.role, UserProfile.Role.PLAYER)
        self.assertEqual(nu.profile.faculty, "IT")
        self.assertEqual(nu.profile.study_group, "ИС-21")
        self.assertEqual(nu.profile.course, "2")
        self.assertEqual(nu.profile.age, 19)

    def test_register_email_domain(self):
        r = self.client.post("/register/", {
            "username": "badmail",
            "email": "x@gmail.com",
            "password1": "StrongP@ss123",
            "password2": "StrongP@ss123",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="badmail").exists())

    def test_login_required_profile(self):
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 302)

    def test_profile_authenticated(self):
        self.client.login(username="player1", password="pass123456")
        r = self.client.get("/profile/")
        self.assertEqual(r.status_code, 200)

    def test_player_dashboard(self):
        self.client.login(username="player1", password="pass123456")
        r = self.client.get("/roles/player/")
        self.assertEqual(r.status_code, 200)

    def test_api_matches(self):
        r = self.client.get("/api/matches/")
        self.assertEqual(r.status_code, 200)

    def test_api_leagues(self):
        r = self.client.get("/api/leagues/")
        self.assertEqual(r.status_code, 200)


class ManagerFlowTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user("mgr", "m@t.com", "pass123456")
        UserProfile.objects.create(user=self.manager, role=UserProfile.Role.MANAGER)
        self.league = League.objects.create(
            sport=League.Sport.FOOTBALL, status=League.Status.ACTIVE, manager=self.manager,
        )
        self.team_a = Team.objects.create(name="Alpha", faculty=Team.Faculty.IT)
        self.team_b = Team.objects.create(name="Beta", faculty=Team.Faculty.LAW)
        self.client = Client()
        self.client.login(username="mgr", password="pass123456")

    def test_manager_dashboard(self):
        r = self.client.get("/roles/manager/")
        self.assertEqual(r.status_code, 200)

    def test_staff_manager_sees_assigned_leagues(self):
        self.manager.is_staff = True
        self.manager.save(update_fields=["is_staff"])
        r_coach = self.client.get("/manage/coaches/")
        self.assertEqual(r_coach.status_code, 200)
        self.assertContains(r_coach, f'value="{self.league.pk}"')
        r_match = self.client.get("/matches/create/")
        self.assertEqual(r_match.status_code, 200)
        self.assertContains(r_match, f'value="{self.league.pk}"')
        r_ann = self.client.get("/announcements/create/")
        self.assertEqual(r_ann.status_code, 200)
        self.assertContains(r_ann, f'value="{self.league.pk}"')

    def test_create_match(self):
        r = self.client.post("/matches/create/", {
            "league": self.league.pk,
            "home_team": self.team_a.pk,
            "away_team": self.team_b.pk,
            "date_time": "2025-12-01T18:00",
            "location": "Стадион",
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Match.objects.filter(home_team=self.team_a).exists())

    def test_enter_result(self):
        m = Match.objects.create(
            league=self.league, home_team=self.team_a, away_team=self.team_b,
            date_time=timezone.now(), location="Test",
        )
        r = self.client.post(f"/matches/{m.pk}/result/", {
            "score_home": 3, "score_away": 1,
        })
        m.refresh_from_db()
        self.assertEqual(m.score_home, 3)
        self.assertEqual(m.status, Match.Status.COMPLETED)
