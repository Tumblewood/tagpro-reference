from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0029_remove_game_replay"),
    ]

    operations = [
        migrations.AddField(
            model_name="season",
            name="uses_halves",
            field=models.BooleanField(
                default=False,
                help_text="Whether this season uses the halves format (e.g., NALTP S26 and earlier)",
            ),
        ),
    ]
