import django_tables2 as tables
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from dcim.models import Device
from netbox.tables import NetBoxTable, columns

from .models import NamingRule


class NamingRuleTable(NetBoxTable):
    name = tables.Column(linkify=True)
    enabled = columns.BooleanColumn()
    object_type = columns.ChoiceFieldColumn(verbose_name=_('Names'))
    template = tables.Column(attrs={'td': {'class': 'font-monospace'}})
    roles = columns.ManyToManyColumn(linkify_item=True)
    device_types = columns.ManyToManyColumn(linkify_item=True)
    sites = columns.ManyToManyColumn(linkify_item=True)
    match_tags = columns.ManyToManyColumn(verbose_name=_('Tags'))
    number_source = columns.ChoiceFieldColumn()
    enforcement = columns.ChoiceFieldColumn()
    fill_gaps = columns.BooleanColumn()
    tags = columns.TagColumn(url_name='plugins:netbox_naming_convention:namingrule_list')

    class Meta(NetBoxTable.Meta):
        model = NamingRule
        fields = (
            'pk', 'id', 'name', 'enabled', 'priority', 'object_type', 'template', 'roles', 'device_types', 'sites', 'match_tags',
            'number_source', 'number_digits', 'number_first', 'number_last', 'fill_gaps', 'number_scope',
            'enforcement', 'description', 'tags', 'created', 'last_updated',
        )
        default_columns = (
            'pk', 'name', 'enabled', 'priority', 'object_type', 'template', 'roles', 'device_types', 'sites', 'match_tags',
            'enforcement',
        )


class RuleObjectTable(NetBoxTable):
    """Objects of a rule whose names don't follow it. Shows the columns of the rule's kind (Kind.columns)."""
    pk = columns.ToggleColumn()
    name = tables.Column(linkify=True)
    site = tables.Column(linkify=True)
    location = tables.Column(linkify=True)
    rack = tables.Column(linkify=True)
    cluster = tables.Column(linkify=True)
    role = tables.Column(linkify=True)
    suggested = tables.Column(verbose_name=_('Suggested name'), orderable=False, empty_values=())

    class Meta(NetBoxTable.Meta):
        model = Device
        fields = ('pk', 'name', 'site', 'location', 'rack', 'cluster', 'role', 'suggested')
        default_columns = fields

    def __init__(self, data, kind, **kwargs):
        hidden = [name for name in ('site', 'location', 'rack', 'cluster', 'role') if name not in kind.columns]
        super().__init__(data, exclude=hidden + ['id', 'actions'], **kwargs)
        # NetBox hides the checkboxes unless a list view turns them on.
        self.columns.show('pk')

    def render_suggested(self, record):
        return getattr(record, 'suggested_name', None) or '—'


class ReportObjectTable(RuleObjectTable):
    """Objects listed on the naming report, with the rule that names them."""
    rule = tables.Column(verbose_name=_('Rule'), orderable=False, empty_values=())

    class Meta(RuleObjectTable.Meta):
        fields = ('pk', 'name', 'site', 'location', 'rack', 'cluster', 'role', 'rule', 'suggested')
        default_columns = fields

    def render_rule(self, record):
        rule = getattr(record, 'naming_rule', None)
        return format_html('<a href="{}">{}</a>', rule.get_absolute_url(), rule) if rule else '—'
