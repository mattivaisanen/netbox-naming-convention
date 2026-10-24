"""
The kinds of objects a rule can name: devices, virtual machines and racks.

Everything that differs between them lives here, so the rest of the plugin
asks the rule's kind instead of knowing about devices:

- which conditions a rule of that kind has, and where on the object each
  one is read (`Condition`);
- where a template value may start (`roots`) and what the object itself
  offers (`own_root`, `own_attributes`);
- what a rule can wait for, which statuses exist, whether the number can
  come from a primary IP;
- the NetBox pages that get the name helper, and the import page renames go
  through.

To support another kind, add a `Kind` to `KINDS` and a condition field to
NamingRule for each of its own related objects.
"""
from dataclasses import dataclass, field

from django.apps import apps
from django.utils.translation import gettext_lazy as _

from dcim.choices import DeviceStatusChoices, RackStatusChoices
from utilities.choices import ChoiceSet
from virtualization.choices import VirtualMachineStatusChoices

__all__ = ('Condition', 'Kind', 'KINDS', 'ObjectTypeChoices', 'DEVICE', 'VIRTUAL_MACHINE', 'RACK', 'kind_of')


@dataclass(frozen=True)
class Condition:
    """A many-to-many field of NamingRule, and where an object keeps that value."""
    field: str
    #: From the object to the related object, such as ('site', 'region').
    path: tuple
    #: Children match too (roles, regions, site groups, locations).
    tree: bool = False


_SITE = (
    Condition('sites', ('site',)),
    Condition('regions', ('site', 'region'), tree=True),
    Condition('site_groups', ('site', 'group'), tree=True),
)


@dataclass(frozen=True)
class Kind:
    key: str
    model_label: str
    label: str
    label_plural: str
    conditions: tuple
    #: Condition fields of which a rule needs at least one (empty: none needed).
    required_conditions: tuple
    #: Where a template value may start, and how to get there from the object.
    roots: dict
    #: The root that stands for the object itself ({device.serial}).
    own_root: str
    #: What the object itself offers in a template, besides cf.<name>.
    own_attributes: frozenset
    #: RequiredValueChoices a rule of this kind can wait for, and the default.
    wait_for: tuple
    default_wait_for: tuple
    statuses: type
    #: The number can come from the object's primary IP.
    has_primary_ip: bool
    #: NetBox requires a name (devices may have none).
    name_required: bool
    max_name: int
    #: The object's fields the name helper sends to the suggest API.
    form_fields: tuple
    #: The fields an add form needs before a rule can match (the helper waits for them).
    kind_fields: tuple = ()
    #: url names: add and edit form, CSV import.
    add_view: str = ''
    edit_view: str = ''
    import_view: str = ''
    #: Columns of the rule page's table of objects that don't follow the rule.
    columns: tuple = field(default=())

    @property
    def model(self):
        return apps.get_model(self.model_label)

    @property
    def condition_fields(self):
        return tuple(c.field for c in self.conditions) + ('match_tags',)

    def condition_errors(self, values):
        """
        Errors of a rule's conditions ({field: values}, as the form or API
        has them): conditions this kind has no use for, and a missing role
        or device type for devices.
        """
        from .models import NamingRule

        errors = {}
        for name, chosen in values.items():
            if chosen and name not in self.condition_fields:
                label = NamingRule._meta.get_field(name).verbose_name
                errors[name] = _('{kinds} have no {field}.').format(
                    kinds=str(self.label_plural).capitalize(), field=label,
                )
        if self.required_conditions and not any(values.get(name) for name in self.required_conditions):
            errors[self.required_conditions[0]] = _('A device rule needs at least one role or device type.')
        return errors


DEVICE = Kind(
    key='device',
    model_label='dcim.device',
    label=_('Device'),
    label_plural=_('devices'),
    conditions=(
        Condition('roles', ('role',), tree=True),
        Condition('device_types', ('device_type',)),
        *_SITE,
        Condition('locations', ('location',), tree=True),
        Condition('tenants', ('tenant',)),
        Condition('platforms', ('platform',)),
    ),
    required_conditions=('roles', 'device_types'),
    roots={
        'site': ('site',),
        'location': ('location',),
        'rack': ('rack',),
        'role': ('role',),
        'device_type': ('device_type',),
        'manufacturer': ('device_type', 'manufacturer'),
        'tenant': ('tenant',),
        'platform': ('platform',),
        'region': ('site', 'region'),
        'site_group': ('site', 'group'),
        'device': (),
    },
    own_root='device',
    own_attributes=frozenset({'serial', 'asset_tag', 'label'}),
    wait_for=('site', 'location', 'rack', 'role', 'device_type', 'tenant', 'platform', 'serial', 'asset_tag'),
    default_wait_for=('site', 'role', 'device_type'),
    statuses=DeviceStatusChoices,
    has_primary_ip=True,
    name_required=False,
    max_name=64,
    form_fields=('site', 'location', 'rack', 'role', 'device_type', 'tenant', 'platform', 'status', 'serial',
                 'asset_tag', 'primary_ip4', 'primary_ip6'),
    kind_fields=('role', 'device_type'),
    add_view='dcim:device_add',
    edit_view='dcim:device_edit',
    import_view='dcim:device_bulk_import',
    columns=('site', 'rack', 'role'),
)

VIRTUAL_MACHINE = Kind(
    key='virtualmachine',
    model_label='virtualization.virtualmachine',
    label=_('Virtual machine'),
    label_plural=_('virtual machines'),
    conditions=(
        Condition('roles', ('role',), tree=True),
        Condition('vm_types', ('virtual_machine_type',)),
        Condition('clusters', ('cluster',)),
        *_SITE,
        Condition('tenants', ('tenant',)),
        Condition('platforms', ('platform',)),
    ),
    required_conditions=(),
    roots={
        'site': ('site',),
        'cluster': ('cluster',),
        'cluster_type': ('cluster', 'type'),
        'cluster_group': ('cluster', 'group'),
        'role': ('role',),
        'vm_type': ('virtual_machine_type',),
        'tenant': ('tenant',),
        'platform': ('platform',),
        'region': ('site', 'region'),
        'site_group': ('site', 'group'),
        'vm': (),
    },
    own_root='vm',
    own_attributes=frozenset({'serial'}),
    wait_for=('site', 'cluster', 'role', 'virtual_machine_type', 'tenant', 'platform', 'serial'),
    default_wait_for=(),
    statuses=VirtualMachineStatusChoices,
    has_primary_ip=True,
    name_required=True,
    max_name=64,
    form_fields=('site', 'cluster', 'role', 'virtual_machine_type', 'tenant', 'platform', 'status', 'serial',
                 'primary_ip4', 'primary_ip6'),
    add_view='virtualization:virtualmachine_add',
    edit_view='virtualization:virtualmachine_edit',
    import_view='virtualization:virtualmachine_bulk_import',
    columns=('site', 'cluster', 'role'),
)

RACK = Kind(
    key='rack',
    model_label='dcim.rack',
    label=_('Rack'),
    label_plural=_('racks'),
    conditions=(
        Condition('rack_roles', ('role',)),
        Condition('rack_types', ('rack_type',)),
        *_SITE,
        Condition('locations', ('location',), tree=True),
        Condition('tenants', ('tenant',)),
    ),
    required_conditions=(),
    roots={
        'site': ('site',),
        'location': ('location',),
        'role': ('role',),
        'rack_type': ('rack_type',),
        'manufacturer': ('rack_type', 'manufacturer'),
        'tenant': ('tenant',),
        'region': ('site', 'region'),
        'site_group': ('site', 'group'),
        'rack': (),
    },
    own_root='rack',
    own_attributes=frozenset({'facility_id', 'serial', 'asset_tag'}),
    wait_for=('site', 'location', 'role', 'rack_type', 'tenant', 'facility_id', 'serial', 'asset_tag'),
    default_wait_for=('site',),
    statuses=RackStatusChoices,
    has_primary_ip=False,
    name_required=True,
    max_name=100,
    form_fields=('site', 'location', 'role', 'rack_type', 'tenant', 'status', 'facility_id', 'serial',
                 'asset_tag'),
    add_view='dcim:rack_add',
    edit_view='dcim:rack_edit',
    import_view='dcim:rack_bulk_import',
    columns=('site', 'location', 'role'),
)

KINDS = {kind.key: kind for kind in (DEVICE, VIRTUAL_MACHINE, RACK)}

_BY_LABEL = {kind.model_label: kind for kind in KINDS.values()}


def kind_of(obj):
    """The Kind of a model instance or class, or None for anything else."""
    return _BY_LABEL.get(obj._meta.label_lower)


class ObjectTypeChoices(ChoiceSet):
    DEVICE = 'device'
    VIRTUAL_MACHINE = 'virtualmachine'
    RACK = 'rack'

    CHOICES = (
        (DEVICE, _('Device'), 'blue'),
        (VIRTUAL_MACHINE, _('Virtual machine'), 'purple'),
        (RACK, _('Rack'), 'orange'),
    )
