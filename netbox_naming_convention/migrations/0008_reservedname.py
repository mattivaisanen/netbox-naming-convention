"""Names reserved ahead of time (ReservedName)."""

import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_naming_convention", "0007_namingseries_released"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReservedName",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False
                    ),
                ),
                ("object_type", models.CharField(max_length=30)),
                ("name", models.CharField(max_length=100)),
                ("series", models.CharField(blank=True, max_length=255)),
                ("number", models.PositiveIntegerField(blank=True, null=True)),
                ("expires", models.DateField(blank=True, null=True)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("created_by", models.CharField(blank=True, max_length=150)),
                ("created", models.DateTimeField(auto_now_add=True)),
                (
                    "rule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reserved_names",
                        to="netbox_naming_convention.namingrule",
                    ),
                ),
            ],
            options={
                "verbose_name": "reserved name",
                "verbose_name_plural": "reserved names",
                "ordering": ("name",),
                "constraints": [
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("object_type"),
                        name="netbox_naming_convention_reserved_name",
                    )
                ],
            },
        ),
    ]
