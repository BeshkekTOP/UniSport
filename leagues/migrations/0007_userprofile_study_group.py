from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("leagues", "0006_remove_captain_role_merge_coach"),
    ]

    operations = [
        migrations.AddField(
            model_name="userprofile",
            name="study_group",
            field=models.CharField(
                blank=True,
                default="",
                max_length=64,
                verbose_name="группа",
            ),
        ),
        migrations.AlterField(
            model_name="userprofile",
            name="faculty",
            field=models.CharField(
                blank=True,
                default="",
                max_length=10,
                verbose_name="факультет",
            ),
        ),
    ]
