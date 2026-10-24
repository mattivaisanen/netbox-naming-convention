import csv
import io
from collections import OrderedDict

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View

from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, preview, reference, tables
from .kinds import KINDS
from .matching import find_rule, ordered_rules, rule_objects, rules_queryset
from .models import NamingRule, NamingSeries
from .naming import _number_of, _render, follows, suggest

#: Most objects a rule page looks at.
RULE_PAGE_LIMIT = 2000
#: Most objects the rule page lists (with a suggested name) as not following the rule.
DRIFTED_SHOWN = 100


@register_model_view(NamingRule, 'list', path='', detail=False)
class NamingRuleListView(generic.ObjectListView):
    queryset = NamingRule.objects.prefetch_related('roles', 'device_types', 'sites', 'match_tags', 'tags')
    table = tables.NamingRuleTable
    filterset = filtersets.NamingRuleFilterSet
    filterset_form = forms.NamingRuleFilterForm


def rule_overview(rule):
    """The series a rule's objects are in, and the objects that don't follow it."""
    objects = rule_objects(rule, limit=RULE_PAGE_LIMIT)
    series = OrderedDict()
    drifted = []
    for obj in objects:
        out, has_number = _render(obj, rule)
        if has_number and out.series and not out.error:
            entry = series.setdefault(out.series, {
                'key': out.series, 'prefix': out.prefix, 'suffix': out.suffix, 'count': 0, 'highest': None,
                'example': obj,
            })
            number = _number_of(obj.name, out.prefix, out.suffix, rule.number_scope)
            if number is not None:
                entry['count'] += 1
                entry['highest'] = max(entry['highest'] or 0, number)
        _rule, fits = follows(obj, rule)
        if not fits:
            drifted.append(obj)
    # A suggestion costs a few queries: only for the objects the page lists.
    for obj in drifted[:DRIFTED_SHOWN]:
        hint = suggest(obj, rule)
        obj.suggested_name = hint.name if hint.ready else None
    stored = dict(NamingSeries.objects.filter(key__in=list(series)).values_list('key', 'high_water'))
    for entry in series.values():
        entry['high_water'] = stored.get(entry['key'], 0)
        if entry['highest'] is not None:
            entry['highest_text'] = rule.format_number(entry['highest'])
        hint = suggest(entry['example'], rule, keep_current=False)
        entry['next'] = hint.name if hint.ready else hint.error
    return {
        'object_count': len(objects),
        'truncated': len(objects) >= RULE_PAGE_LIMIT,
        'series': list(series.values()),
        'drifted': drifted,
    }


@register_model_view(NamingRule)
class NamingRuleView(generic.ObjectView):
    queryset = NamingRule.objects.prefetch_related(*NamingRule.CONDITION_FIELDS)

    def get_extra_context(self, request, instance):
        kind = instance.kind
        overview = rule_overview(instance)
        table = tables.RuleObjectTable(overview['drifted'][:DRIFTED_SHOWN], kind, orderable=False)
        app_label, model_name = kind.model_label.split('.')
        conditions = [
            (instance._meta.get_field(name).verbose_name, getattr(instance, name).all())
            for name in kind.condition_fields if name != 'match_tags'
        ]
        return {
            **overview, 'kind': kind, 'conditions': conditions, 'drifted_table': table,
            'drifted_count': len(overview['drifted']), 'can_rename': request.user.has_perm(f'{app_label}.change_{model_name}'),
        }


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


@register_model_view(NamingRule, 'preview', path='preview', detail=False)
class NamingRulePreviewView(LoginRequiredMixin, View):
    """
    The rule form posts itself here whenever it changes; the answer is the
    preview below *Try on* (see preview.py). Saves nothing.
    """
    def post(self, request):
        user = request.user
        rule = None
        if request.GET.get('rule', '').isdigit():
            rule = get_object_or_404(NamingRule.objects.restrict(user, 'change'), pk=request.GET['rule'])
        elif not user.has_perm('netbox_naming_convention.add_namingrule'):
            raise PermissionDenied
        form = forms.NamingRuleForm(data=request.POST, instance=rule)
        form.is_valid()
        obj = form.cleaned_data.get('preview_object')
        if obj is not None and not type(obj).objects.restrict(user, 'view').filter(pk=obj.pk).exists():
            obj = None
        context = preview.preview(form, user, obj)
        return render(request, 'netbox_naming_convention/inc/rule_preview.html', context)


class TemplateReferenceView(LoginRequiredMixin, View):
    """Everything a template can use, per object type (?object_type=). Linked from the rule form."""
    def get(self, request):
        kind = KINDS.get(request.GET.get('object_type')) or KINDS['device']
        return render(request, 'netbox_naming_convention/reference.html', {
            'kind': kind, 'kinds': KINDS.values(), 'values': reference.VALUES[kind.key],
            'filters': reference.FILTERS, 'other': reference.OTHER,
        })


#: Most objects renamed in one go.
RENAME_LIMIT = 500


def rename_plan(rule, objects):
    """
    (rows, skipped): the new name of each object that doesn't follow `rule`,
    numbers kept distinct within the batch, and the objects that can't be
    renamed with why.
    """
    rows, skipped, taken = [], [], {}
    rules = ordered_rules(rules_queryset(rule.kind))  # once, not per object
    for obj in objects:
        if find_rule(obj, rules) != rule:
            skipped.append((obj, _('Another rule names this {kind}.').format(kind=rule.kind.label.lower())))
            continue
        hint = suggest(obj, rule, taken=taken)
        if not hint.ready:
            reason = hint.error or _('Waiting for: {missing}').format(missing=', '.join(hint.missing))
            skipped.append((obj, reason))
            continue
        if hint.name == obj.name:
            continue
        if hint.number is not None:
            taken.setdefault(hint.series, set()).add(hint.number)
        rows.append((obj, hint.name))
    return rows, skipped


@register_model_view(NamingRule, 'rename', path='rename')
class NamingRuleRenameView(LoginRequiredMixin, View):
    """
    Rename objects to their rule's name: shows old and new names, and the
    confirm button sends them to NetBox's own import for that kind of object
    (id,name), so permissions, the change log and netbox-change-approval
    work as for any bulk edit.
    """
    def post(self, request, pk):
        rule = get_object_or_404(NamingRule.objects.restrict(request.user, 'view'), pk=pk)
        kind = rule.kind
        pks = [value for value in request.POST.getlist('pk') if value.isdigit()][:RENAME_LIMIT]
        related = [path for path in ('__'.join(root) for root in kind.roots.values()) if path]
        if kind.has_primary_ip:
            related += ['primary_ip4', 'primary_ip6']
        objects = kind.model.objects.restrict(request.user, 'change').filter(pk__in=pks).select_related(
            *related,
        ).order_by('name', 'pk')
        rows, skipped = rename_plan(rule, list(objects))
        out = io.StringIO()
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(('id', 'name'))
        writer.writerows((obj.pk, name) for obj, name in rows)
        return render(request, 'netbox_naming_convention/rename.html', {
            'object': rule, 'kind': kind, 'rows': rows, 'skipped': skipped, 'data': out.getvalue(),
            'import_url': reverse(kind.import_view),
        })
