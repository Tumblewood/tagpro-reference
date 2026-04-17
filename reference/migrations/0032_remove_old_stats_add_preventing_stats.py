from django.db import migrations, models

REMOVE_FIELDS = ["quick_caps", "resets", "chained_holds"]
ADD_FIELDS = ["preventing_opponents", "preventing_teammates"]
MODELS = ["PlayerStats", "PlayerRegulationStats"]


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0031_new_stat_fields"),
    ]

    operations = [
        op
        for model in MODELS
        for field in REMOVE_FIELDS
        for op in [
            migrations.RemoveField(
                model_name=model.lower(),
                name=field,
            )
        ]
    ] + [
        op
        for model in MODELS
        for field in ADD_FIELDS
        for op in [
            migrations.AddField(
                model_name=model.lower(),
                name=field,
                field=models.IntegerField(blank=True, null=True),
            )
        ]
    ]
