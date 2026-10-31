"""Rules get a member suffix: names of stack members such as SW005-1 follow the rule."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_naming_convention", "0005_object_types"),
    ]

    operations = [
        migrations.AddField(
            model_name="namingrule",
            name="member_suffix",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
