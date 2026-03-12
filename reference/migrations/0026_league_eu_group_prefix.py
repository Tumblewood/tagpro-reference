from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0025_awardtype_recipient_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="league",
            name="eu_group_prefix",
            field=models.CharField(
                blank=True,
                help_text="Prefix used in tagpro.eu group names for teams in this league (e.g. 'M' for MLTP, 'N' for mLTP, 'A' for NLTP)",
                max_length=5,
                null=True,
            ),
        ),
    ]
