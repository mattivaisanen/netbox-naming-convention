"""
The preview on the rule form: the names a rule would give, while it is
being written. Nothing is saved or reserved.

The preview builds the rule as the form has it (`rule_draft()`) and runs
the same code as everything else (matching.rule_objects(), naming.suggest()).
The draft is an unsaved NamingRule whose many-to-many conditions are put in
Django's prefetch cache, so `rule.roles.all()` and friends answer from the
form instead of the database.
"""
import re

from django.utils.translation import gettext as _

from .matching import find_rule, rule_matches, rule_objects, rules_queryset
from .naming import render_name, suggest

#: Objects of the rule shown in the preview.
PREVIEW_LIMIT = 10

#: Fields of the rule form whose errors make the preview pointless.
NAME_FIELDS = ('template', 'name_filters', 'ip_pattern', 'skip_numbers', 'number_digits', 'number_last',
               'member_suffix')

#: Stands in for the primary key of a rule not saved yet (Django needs one
#: before many-to-many values can be read; no rule has 0).
UNSAVED_PK = 0


def rule_draft(form):
    """The rule as `form` (a validated NamingRuleForm) has it, enabled."""
    rule = form.instance
    if rule.pk is None:
        rule.pk = UNSAVED_PK
    rule.enabled = True
    cache = {}
    for name in rule.CONDITION_FIELDS:
        model = rule._meta.get_field(name).related_model
        # Conditions the object type has no use for are not on the form.
        values = form.cleaned_data.get(name) or []
        queryset = model.objects.filter(pk__in=[value.pk for value in values])
        list(queryset)  # fills the queryset's cache, so .all() and .exists() don't query again
        cache[name] = queryset
    rule._prefetched_objects_cache = cache
    return rule


def pattern_parts(pattern):
    """[(text, missing)]: AMS1-SW###-<rack.name> as pieces, the values not known yet marked."""
    return [(piece, bool(i % 2)) for i, piece in enumerate(re.split(r'<([^<>]+)>', pattern)) if piece]


def _row(obj, hint):
    if hint.error:
        note = hint.error
    elif hint.missing:
        note = _('Waiting for: {missing}').format(missing=', '.join(hint.missing))
    elif hint.name == obj.name:
        note = _('Unchanged')
    else:
        note = ''
    return {'object': obj, 'name': hint.name if hint.ready else None, 'note': note}


def _tried(obj, rule):
    """The preview for the object picked on the form: its name, and whether this rule names it."""
    kind = rule.kind.label.lower()
    if not rule_matches(rule, obj):
        why = _('This {kind} doesn\'t match the rule\'s conditions; this is the name the template gives it.').format(
            kind=kind,
        )
    else:
        rules = [r for r in rules_queryset(rule.kind) if r.pk != rule.pk] + [rule]
        first = find_rule(obj, rules)
        if first is rule:
            why = None
        else:
            why = _('The rule "{rule}" names this {kind} first.').format(rule=first, kind=kind)
    return {**_row(obj, suggest(obj, rule)), 'why': why}


def preview(form, user, obj=None):
    """
    What the preview card shows for the rule form `form` (already
    validated). `obj` is the object picked in "Try on", of the rule's kind.
    """
    if not form.data.get('template'):
        return {'errors': [_('Type a template to see the names it gives.')]}
    errors = [error for name in NAME_FIELDS for error in form.errors.get(name, [])]
    if errors:
        return {'errors': errors}
    rule = rule_draft(form)
    model = rule.kind.model
    out, _has_number = render_name(obj or model(), rule)
    if out.error:
        return {'errors': [out.error]}
    visible = model.objects.restrict(user, 'view')
    objs = rule_objects(rule, limit=PREVIEW_LIMIT, objects=visible)
    taken, rows = {}, []
    for each in objs:
        hint = suggest(each, rule, taken=taken)
        if hint.ready and hint.number is not None:
            taken.setdefault(hint.series, set()).add(hint.number)
        rows.append(_row(each, hint))
    return {
        'pattern': pattern_parts(out.pattern),
        'tried': _tried(obj, rule) if obj is not None else None,
        'rows': rows,
        'more': len(objs) >= PREVIEW_LIMIT,
        'kind': rule.kind,
        'needs_kind': bool(rule.kind.required_conditions) and not any(
            form.cleaned_data.get(name) for name in rule.kind.required_conditions
        ),
    }
