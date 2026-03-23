from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm

from .models import UserProfile


class RegistrationForm(UserCreationForm):
    role = forms.ChoiceField(choices=UserProfile.Role.choices, label="Роль")
    first_name = forms.CharField(max_length=150, required=False, label="Имя")
    last_name = forms.CharField(max_length=150, required=False, label="Фамилия")
    email = forms.EmailField(required=False, label="Email")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role", "password1", "password2")
