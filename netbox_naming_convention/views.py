import csv
import io
from collections import OrderedDict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from dcim.models import Device
from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, reference, tables
from .matching import find_rule, ordered_rules, rule_devices
from .models import NamingRule, NamingSeries
from .naming import _number_of, _render, follows, suggest

#: Most devices a rule page looks at.
RULE_PAGE_LIMIT = 2000
#: Most devices the rule page lists (with a suggested name) as not following the rule.
DRIFTED_SHOWN = 100


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
            drifted.append(device)
    # A suggestion costs a few queries: only for the devices the page lists.
    for device in drifted[:DRIFTED_SHOWN]:
        hint = suggest(device, rule)
        device.suggested_name = hint.name if hint.ready else None
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
        table = tables.RuleDeviceTable(overview['drifted'][:DRIFTED_SHOWN], orderable=False)
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



class TemplateReferenceView(LoginRequiredMixin, View):
    """Everything a template can use. Linked from the rule form."""
    def get(self, request):
        return render(request, 'netbox_naming_convention/reference.html', {
            'values': reference.VALUES, 'filters': reference.FILTERS, 'other': reference.OTHER,
        })


#: Most devices renamed in one go.
RENAME_LIMIT = 500


def rename_plan(rule, devices):
    """
    (rows, skipped): the new name of each device that doesn't follow `rule`,
    numbers kept distinct within the batch, and the devices that can't be
    renamed with why.
    """
    rows, skipped, taken = [], [], {}
    rules = ordered_rules()  # once, not per device
    for device in devices:
        if find_rule(device, rules) != rule:
            skipped.append((device, _('Another rule names this device.')))
            continue
        hint = suggest(device, rule, taken=taken)
        if not hint.ready:
            reason = hint.error or _('Waiting for: {missing}').format(missing=', '.join(hint.missing))
            skipped.append((device, reason))
            continue
        if hint.name == device.name:
            continue
        if hint.number is not None:
            taken.setdefault(hint.series, set()).add(hint.number)
        rows.append((device, hint.name))
    return rows, skipped


@register_model_view(NamingRule, 'rename', path='rename')
class NamingRuleRenameView(LoginRequiredMixin, View):
    """
    Rename devices to their rule's name: shows old and new names, and the
    confirm button sends them to NetBox's own device import (id,name), so
    permissions, the change log and netbox-change-approval work as for any
    bulk edit.
    """
    def post(self, request, pk):
        rule = get_object_or_404(NamingRule.objects.restrict(request.user, 'view'), pk=pk)
        pks = [value for value in request.POST.getlist('pk') if value.isdigit()][:RENAME_LIMIT]
        devices = Device.objects.restrict(request.user, 'change').filter(pk__in=pks).select_related(
            'site', 'location', 'rack', 'role', 'device_type__manufacturer', 'tenant', 'platform',
            'primary_ip4', 'primary_ip6',
        ).order_by('name', 'pk')
        rows, skipped = rename_plan(rule, list(devices))
        out = io.StringIO()
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(('id', 'name'))
        writer.writerows((device.pk, name) for device, name in rows)
        return render(request, 'netbox_naming_convention/rename.html', {
            'object': rule, 'rows': rows, 'skipped': skipped, 'data': out.getvalue(),
            'import_url': reverse('dcim:device_bulk_import'),
        })
