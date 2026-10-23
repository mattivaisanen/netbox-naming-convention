from collections import OrderedDict

from django.utils.translation import gettext_lazy as _

from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, tables
from .matching import rule_devices
from .models import NamingRule, NamingSeries
from .naming import _number_of, _render, follows, suggest

#: Most devices a rule page looks at.
RULE_PAGE_LIMIT = 2000


@register_model_view(NamingRule, 'list', path='', detail=False)
class NamingRuleListView(generic.ObjectListView):
    queryset = NamingRule.objects.prefetch_related('roles', 'device_types', 'sites', 'match_tags', 'tags')
    table = tables.NamingRuleTable
    filterset = filtersets.NamingRuleFilterSet
    filterset_form = forms.NamingRuleFilterForm


def rule_overview(rule):
    """The series a rule's devices are in, and the devices that don't follow it."""
    devices = rule_devices(rule, limit=RULE_PAGE_LIMIT)
    series = OrderedDict()
    drifted = []
    for device in devices:
        out, has_number = _render(device, rule)
        if has_number and out.series and not out.error:
            entry = series.setdefault(out.series, {
                'key': out.series, 'prefix': out.prefix, 'suffix': out.suffix, 'count': 0, 'highest': None,
                'example': device,
            })
            number = _number_of(device.name, out.prefix, out.suffix, rule.number_scope)
            if number is not None:
                entry['count'] += 1
                entry['highest'] = max(entry['highest'] or 0, number)
        _rule, fits = follows(device, rule)
        if not fits:
            hint = suggest(device, rule)
            device.suggested_name = hint.name if hint.ready else None
            drifted.append(device)
    stored = dict(NamingSeries.objects.filter(key__in=list(series)).values_list('key', 'high_water'))
    for entry in series.values():
        entry['high_water'] = stored.get(entry['key'], 0)
        if entry['highest'] is not None:
            entry['highest_text'] = rule.format_number(entry['highest'])
        hint = suggest(entry['example'], rule, keep_current=False)
        entry['next'] = hint.name if hint.ready else hint.error
    return {
        'device_count': len(devices),
        'truncated': len(devices) >= RULE_PAGE_LIMIT,
        'series': list(series.values()),
        'drifted': drifted,
    }


@register_model_view(NamingRule)
class NamingRuleView(generic.ObjectView):
    queryset = NamingRule.objects.prefetch_related(
        'roles', 'device_types', 'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms',
        'match_tags',
    )

    def get_extra_context(self, request, instance):
        overview = rule_overview(instance)
        table = tables.RuleDeviceTable(overview['drifted'][:100], orderable=False)
        return {**overview, 'drifted_table': table, 'drifted_count': len(overview['drifted'])}


@register_model_view(NamingRule, 'add', detail=False)
@register_model_view(NamingRule, 'edit')
class NamingRuleEditView(generic.ObjectEditView):
    queryset = NamingRule.objects.all()
    form = forms.NamingRuleForm


@register_model_view(NamingRule, 'delete')
class NamingRuleDeleteView(generic.ObjectDeleteView):
    queryset = NamingRule.objects.all()


@register_model_view(NamingRule, 'bulk_delete', path='delete', detail=False)
class NamingRuleBulkDeleteView(generic.BulkDeleteView):
    queryset = NamingRule.objects.all()
    filterset = filtersets.NamingRuleFilterSet
    table = tables.NamingRuleTable

