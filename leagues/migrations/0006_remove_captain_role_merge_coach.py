from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def forwards(apps, schema_editor):
    UserProfile = apps.get_model("leagues", "UserProfile")
    UserProfile.objects.filter(role="CAPTAIN").update(role="COACH")


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("leagues", "0005_coach_join_models"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="userprofile",
            name="role",
            field=models.CharField(
                choices=[
                    ("MANAGER", "Менеджер"),
                    ("COACH", "Тренер"),
                    ("PLAYER", "Игрок"),
                ],
                default="PLAYER",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="team",
            name="captain",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="captained_teams",
                to=settings.AUTH_USER_MODEL,
                verbose_name="тренер",
            ),
        ),
    ]
