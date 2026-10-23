import django_tables2 as tables
from django.utils.translation import gettext_lazy as _

from dcim.models import Device
from netbox.tables import NetBoxTable, columns

from .models import NamingRule


class NamingRuleTable(NetBoxTable):
    name = tables.Column(linkify=True)
    enabled = columns.BooleanColumn()
    template = tables.Column(attrs={'td': {'class': 'font-monospace'}})
    roles = columns.ManyToManyColumn(linkify_item=True)
    device_types = columns.ManyToManyColumn(linkify_item=True)
    sites = columns.ManyToManyColumn(linkify_item=True)
    match_tags = columns.ManyToManyColumn(verbose_name=_('Device tags'))
    number_source = columns.ChoiceFieldColumn()
    enforcement = columns.ChoiceFieldColumn()
    fill_gaps = columns.BooleanColumn()
    tags = columns.TagColumn(url_name='plugins:netbox_naming_convention:namingrule_list')

    class Meta(NetBoxTable.Meta):
        model = NamingRule
        fields = (
            'pk', 'id', 'name', 'enabled', 'priority', 'template', 'roles', 'device_types', 'sites', 'match_tags',
            'number_source', 'number_digits', 'number_first', 'number_last', 'fill_gaps', 'number_scope',
            'enforcement', 'description', 'tags', 'created', 'last_updated',
        )
        default_columns = (
            'pk', 'name', 'enabled', 'priority', 'template', 'roles', 'device_types', 'sites', 'match_tags',
            'enforcement',
        )


class RuleDeviceTable(NetBoxTable):
    """Devices of a rule whose names don't follow it."""
    pk = columns.ToggleColumn()
    name = tables.Column(linkify=True)
    site = tables.Column(linkify=True)
    rack = tables.Column(linkify=True)
    role = tables.Column(linkify=True)
    suggested = tables.Column(verbose_name=_('Suggested name'), orderable=False, empty_values=())

    class Meta(NetBoxTable.Meta):
        model = Device
        fields = ('pk', 'name', 'site', 'rack', 'role', 'suggested')
        default_columns = fields

    def render_suggested(self, record):
        return getattr(record, 'suggested_name', None) or '—'
