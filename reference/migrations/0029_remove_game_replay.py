from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("reference", "0028_alter_transaction_transaction_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="game",
            name="replay",
        ),
    ]
