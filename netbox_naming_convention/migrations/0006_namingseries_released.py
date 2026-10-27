"""Numbers of devices that were never approved, handed out again first."""
import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_naming_convention", "0005_object_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="namingseries",
            name="released",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.PositiveIntegerField(), blank=True, default=list,
            ),
        ),
    ]
