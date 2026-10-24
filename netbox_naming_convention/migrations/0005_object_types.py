"""
Rules name devices, virtual machines or racks.

- NamingRule gets an object type (existing rules name devices) and the
  conditions of virtual machines and racks.
- Series keys start with the object type ("device:ams1-sw"), so devices and
  racks named alike count separately.
- AssignedName points at any object instead of only a device.
"""
import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    AssignedName = apps.get_model('netbox_naming_convention', 'AssignedName')
    NamingSeries = apps.get_model('netbox_naming_convention', 'NamingSeries')
    device_type, _ = ContentType.objects.get_or_create(app_label='dcim', model='device')
    AssignedName.objects.update(object_type=device_type, object_id=models.F('device_id'))
    for series in NamingSeries.objects.exclude(key__startswith='device:'):
        series.key = f'device:{series.key}'
        series.save(update_fields=('key',))


def backwards(apps, schema_editor):
    AssignedName = apps.get_model('netbox_naming_convention', 'AssignedName')
    NamingSeries = apps.get_model('netbox_naming_convention', 'NamingSeries')
    AssignedName.objects.exclude(object_type__app_label='dcim', object_type__model='device').delete()
    AssignedName.objects.update(device_id=models.F('object_id'))
    NamingSeries.objects.exclude(key__startswith='device:').delete()
    for series in NamingSeries.objects.all():
        series.key = series.key.removeprefix('device:')
        series.save(update_fields=('key',))


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('dcim', '0250_cooling_infrastructure'),
        ('netbox_naming_convention', '0004_namingrule_required_values'),
        ('virtualization', '0060_consolidate_unique_constraints'),
    ]

    operations = [
        migrations.AddField(
            model_name='namingrule',
            name='object_type',
            field=models.CharField(default='device', max_length=30),
        ),
        migrations.AddField(
            model_name='namingrule',
            name='vm_types',
            field=models.ManyToManyField(blank=True, related_name='+', to='virtualization.virtualmachinetype'),
        ),
        migrations.AddField(
            model_name='namingrule',
            name='clusters',
            field=models.ManyToManyField(blank=True, related_name='+', to='virtualization.cluster'),
        ),
        migrations.AddField(
            model_name='namingrule',
            name='rack_roles',
            field=models.ManyToManyField(blank=True, related_name='+', to='dcim.rackrole'),
        ),
        migrations.AddField(
            model_name='namingrule',
            name='rack_types',
            field=models.ManyToManyField(blank=True, related_name='+', to='dcim.racktype'),
        ),
        # AssignedName: from a device to any object.
        migrations.RemoveConstraint(
            model_name='assignedname',
            name='netbox_naming_convention_assigned_name',
        ),
        migrations.AddField(
            model_name='assignedname',
            name='object_type',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+',
                to='contenttypes.contenttype',
            ),
        ),
        migrations.AddField(
            model_name='assignedname',
            name='object_id',
            field=models.PositiveBigIntegerField(null=True),
        ),
        migrations.AlterField(
            model_name='assignedname',
            name='device',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='dcim.device',
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.RemoveField(
            model_name='assignedname',
            name='device',
        ),
        migrations.AlterField(
            model_name='assignedname',
            name='object_type',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name='+', to='contenttypes.contenttype',
            ),
        ),
        migrations.AlterField(
            model_name='assignedname',
            name='object_id',
            field=models.PositiveBigIntegerField(),
        ),
        migrations.AlterField(
            model_name='assignedname',
            name='name',
            field=models.CharField(max_length=100),
        ),
        migrations.AddConstraint(
            model_name='assignedname',
            constraint=models.UniqueConstraint(
                fields=('object_type', 'object_id', 'name'), name='netbox_naming_convention_assigned_name',
            ),
        ),
    ]
