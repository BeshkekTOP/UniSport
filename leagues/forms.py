from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.utils import timezone

from .models import (
    Announcement,
    League,
    Match,
    PlayerAttendance,
    Team,
    UserProfile,
)


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class UserPasswordChangeForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            "old_password": "Текущий пароль",
            "new_password1": "Новый пароль",
            "new_password2": "Подтверждение нового пароля",
        }
        for name, field in self.fields.items():
            field.label = labels.get(name, field.label)
            field.widget.attrs.setdefault("class", "form-control")


class RegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False, label="Имя")
    last_name = forms.CharField(max_length=150, required=False, label="Фамилия")
    email = forms.EmailField(required=True, label="Email")
    faculty = forms.ChoiceField(
        choices=[("", "— выберите факультет —")] + list(Team.Faculty.choices),
        required=True,
        label="Факультет",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    study_group = forms.CharField(
        max_length=64,
        required=True,
        label="Группа (учебная)",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Напр. ИС-21"}),
    )
    course = forms.ChoiceField(
        choices=[("", "— выберите курс —")] + list(UserProfile.Course.choices),
        required=True,
        label="Курс",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    age = forms.IntegerField(
        min_value=15,
        max_value=80,
        required=True,
        label="Возраст",
        widget=forms.NumberInput(attrs={"class": "form-control"}),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "username",
                "first_name",
                "last_name",
                "email",
                "faculty",
                "study_group",
                "course",
                "age",
                "password1",
                "password2",
            ]
        )
        for name, field in self.fields.items():
            if name == "faculty":
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip()
        if not email:
            raise forms.ValidationError("Укажите email.")
        lower = email.lower()
        if not lower.endswith("@rea.ru"):
            raise forms.ValidationError("Регистрация доступна только для адресов @rea.ru.")
        return email

    def clean_study_group(self):
        g = (self.cleaned_data.get("study_group") or "").strip()
        if not g:
            raise forms.ValidationError("Укажите группу.")
        return g


class MatchCreateForm(forms.ModelForm):
    date_time = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-control"}),
        label="Дата и время",
    )

    def __init__(self, *args, league_queryset=None, **kwargs):
        league_queryset = kwargs.pop("league_queryset", league_queryset)
        super().__init__(*args, **kwargs)
        self.fields["date_time"].widget.attrs["min"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
        if league_queryset is not None:
            self.fields["league"].queryset = league_queryset
        league_id = self.data.get("league") or self.initial.get("league")
        if league_id:
            teams_qs = Team.objects.filter(leagues__id=league_id).distinct().order_by("name")
            if teams_qs.exists():
                self.fields["home_team"].queryset = teams_qs
                self.fields["away_team"].queryset = teams_qs

    class Meta:
        model = Match
        fields = ("league", "home_team", "away_team", "date_time", "location")
        widgets = {
            "league": forms.Select(attrs={"class": "form-select"}),
            "home_team": forms.Select(attrs={"class": "form-select"}),
            "away_team": forms.Select(attrs={"class": "form-select"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
        }
        labels = {
            "league": "Лига",
            "home_team": "Команда хозяев",
            "away_team": "Команда гостей",
            "location": "Место проведения",
        }


class MatchResultForm(forms.Form):
    score_home = forms.IntegerField(min_value=0, label="Счёт хозяев", widget=forms.NumberInput(attrs={"class": "form-control"}))
    score_away = forms.IntegerField(min_value=0, label="Счёт гостей", widget=forms.NumberInput(attrs={"class": "form-control"}))


class MatchGoalEventForm(forms.Form):
    scorer = forms.ModelChoiceField(queryset=User.objects.none(), label="Автор гола")
    minute = forms.IntegerField(min_value=1, max_value=200, label="Минута")

    def __init__(self, *args, players_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if players_queryset is not None:
            self.fields["scorer"].queryset = players_queryset
        self.fields["scorer"].widget.attrs.setdefault("class", "form-select")
        self.fields["minute"].widget.attrs.setdefault("class", "form-control")


class AnnouncementForm(forms.ModelForm):
    def __init__(self, *args, league_queryset=None, **kwargs):
        league_queryset = kwargs.pop("league_queryset", league_queryset)
        super().__init__(*args, **kwargs)
        if league_queryset is not None:
            self.fields["league"].queryset = league_queryset

    class Meta:
        model = Announcement
        fields = ("league", "title", "text")
        widgets = {
            "league": forms.Select(attrs={"class": "form-select"}),
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "text": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        labels = {
            "league": "Лига",
            "title": "Заголовок",
            "text": "Текст объявления",
        }


class AttendanceForm(forms.Form):
    status = forms.ChoiceField(
        choices=PlayerAttendance.Reason.choices,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )


class ProfileForm(forms.Form):
    first_name = forms.CharField(max_length=150, required=False, label="Имя")
    last_name = forms.CharField(max_length=150, required=False, label="Фамилия")
    email = forms.EmailField(required=False, label="Email")
    faculty = forms.ChoiceField(
        choices=[("", "— выберите факультет —")] + list(Team.Faculty.choices),
        required=False,
        label="Факультет",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    study_group = forms.CharField(max_length=64, required=False, label="Группа")
    course = forms.ChoiceField(
        choices=[("", "— выберите курс —")] + list(UserProfile.Course.choices),
        required=False,
        label="Курс",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    age = forms.IntegerField(min_value=15, max_value=80, required=False, label="Возраст")
    bio = forms.CharField(required=False, label="Описание", widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}))
    photo = forms.FileField(required=False, label="Фото профиля")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class LeagueForm(forms.ModelForm):
    class Meta:
        model = League
        fields = ("sport", "season", "status", "manager")
        widgets = {
            "sport": forms.Select(attrs={"class": "form-select"}),
            "season": forms.TextInput(attrs={"class": "form-control"}),
            "status": forms.Select(attrs={"class": "form-select"}),
            "manager": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "sport": "Вид спорта",
            "season": "Сезон",
            "status": "Статус",
            "manager": "Менеджер",
        }


class TeamForm(forms.ModelForm):
    league = forms.ModelChoiceField(
        queryset=League.objects.none(),
        required=False,
        label="Лига",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, league_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        if league_queryset is not None:
            self.fields["league"].queryset = league_queryset

    class Meta:
        model = Team
        fields = ("name", "faculty", "course")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "faculty": forms.Select(attrs={"class": "form-select"}),
            "course": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "name": "Название команды",
            "faculty": "Факультет",
            "course": "Курс",
        }


class CoachAssignForm(forms.Form):
    league = forms.ModelChoiceField(queryset=League.objects.none(), label="Лига")
    team = forms.ModelChoiceField(queryset=Team.objects.none(), label="Команда")
    coach = forms.ModelChoiceField(queryset=User.objects.none(), label="Тренер")

    def __init__(self, *args, manager=None, league_queryset=None, **kwargs):
        league_queryset = kwargs.pop("league_queryset", league_queryset)
        manager = kwargs.pop("manager", manager)
        super().__init__(*args, **kwargs)
        if league_queryset is not None:
            leagues = league_queryset
        elif manager is not None:
            leagues = League.objects.filter(manager=manager).order_by("-season", "sport")
        else:
            leagues = League.objects.none()
        self.fields["league"].queryset = leagues
        league_id = None
        if self.data.get("league"):
            league_id = self.data.get("league")
        elif self.initial.get("league"):
            initial_league = self.initial["league"]
            league_id = str(getattr(initial_league, "pk", initial_league))
        if league_id:
            self.fields["team"].queryset = Team.objects.filter(leagues__id=league_id).distinct()
        else:
            self.fields["team"].queryset = Team.objects.filter(leagues__in=leagues).distinct()
        self.fields["coach"].queryset = User.objects.filter(is_active=True).order_by("username")
        for name in ("league", "team", "coach"):
            self.fields[name].widget.attrs.setdefault("class", "form-select")


class AdminUserCreateForm(UserCreationForm):
    role = forms.ChoiceField(choices=UserProfile.Role.choices, label="Роль", widget=forms.Select(attrs={"class": "form-select"}))
    first_name = forms.CharField(max_length=150, required=False, label="Имя")
    last_name = forms.CharField(max_length=150, required=False, label="Фамилия")
    email = forms.EmailField(required=False, label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role", "password1", "password2")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "role":
                continue
            field.widget.attrs.setdefault("class", "form-control")


class AdminUserUpdateForm(forms.ModelForm):
    role = forms.ChoiceField(choices=UserProfile.Role.choices, label="Роль", widget=forms.Select(attrs={"class": "form-select"}))

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "is_active")
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "first_name": "Имя",
            "last_name": "Фамилия",
            "email": "Email",
            "is_active": "Активен",
        }


class UserRoleForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("role",)
        widgets = {"role": forms.Select(attrs={"class": "form-select"})}
        labels = {"role": "Роль в системе"}
