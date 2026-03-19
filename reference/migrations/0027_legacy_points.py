from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0026_league_eu_group_prefix"),
    ]

    operations = [
        migrations.AddField(
            model_name="league",
            name="legacy_weight",
            field=models.FloatField(
                default=0,
                help_text="Multiplier applied to legacy points for seasons in this league. 0 means legacy points are not calculated.",
            ),
        ),
        migrations.AddField(
            model_name="awardtype",
            name="legacy_value",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Legacy points this award conveys to first place. Second gets 40%, third gets 20%.",
            ),
        ),
        migrations.AddField(
            model_name="playerseason",
            name="legacy_points",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Calculated legacy points for this player-season.",
            ),
        ),
    ]
