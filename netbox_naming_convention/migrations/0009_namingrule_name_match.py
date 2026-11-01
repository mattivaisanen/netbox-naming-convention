"""Rules get a name match: names may have other text before or after the rule's name."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_naming_convention", "0008_reservedname"),
    ]

    operations = [
        migrations.AddField(
            model_name="namingrule",
            name="name_match",
            field=models.CharField(default="exact", max_length=10),
        ),
    ]
