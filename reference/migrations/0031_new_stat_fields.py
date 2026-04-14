from django.db import migrations, models


NEW_INT_FIELDS = [
    "near_caps",
    "quick_caps",
    "outs",
    "productive_grabs",
    "chained_holds",
    "grabs_against",
    "outs_against",
    "resets",
    "tp",
    "rb",
    "jj",
    "ntpops",
    "ot_caps",
]


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0030_season_uses_halves"),
    ]

    operations = [
        # Add new integer fields to PlayerStats
        *[
            migrations.AddField(
                model_name="playerstats",
                name=field,
                field=models.IntegerField(blank=True, null=True),
            )
            for field in NEW_INT_FIELDS
        ],
        # Add new integer fields to PlayerRegulationStats
        *[
            migrations.AddField(
                model_name="playerregulationstats",
                name=field,
                field=models.IntegerField(blank=True, null=True),
            )
            for field in NEW_INT_FIELDS
        ],
        # Add float fields to PlayerRegulationStats only
        migrations.AddField(
            model_name="playerregulationstats",
            name="tscar",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Total Simple Caps Above Replacement (OSCAR + DSCAR)",
            ),
        ),
        migrations.AddField(
            model_name="playerregulationstats",
            name="ba_time_played",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Blowout-adjusted time played (minutes)",
            ),
        ),
        migrations.AddField(
            model_name="playerregulationstats",
            name="ba_pm",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text="Blowout-adjusted plus/minus",
            ),
        ),
    ]
