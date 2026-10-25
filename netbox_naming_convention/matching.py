"""
Which rule names an object (a device, virtual machine or rack).

Matching works on the object as it is in memory, because an object being
created has no database row yet: its role, site, rack and so on are read from
the instance, its tags from what the form or the API is about to save
(`instance._m2m_values['tags']`, set by NetBox before validation) or, for a
saved object without such values, from the database.

Only rules for the object's kind are tried (kinds.py). Rules are checked by
priority (then name); the first enabled rule whose conditions all match wins.
Within a condition any listed value matches. Roles, regions and locations
match their children too.
"""
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Manager

from .kinds import DEVICE, kind_of, prepare
from .models import NamingRule, TagMatchChoices

__all__ = (
    'find_rule', 'rule_matches', 'object_tag_slugs', 'rules_queryset', 'ordered_rules', 'rule_objects',
    'related_object',
)

_LOOKUPS = {
    'exact', 'iexact', 'in', 'isnull', 'gt', 'gte', 'lt', 'lte',
    'contains', 'icontains', 'startswith', 'istartswith', 'endswith', 'iendswith',
}


def rules_queryset(kind=None):
    """Enabled rules, of one kind (kinds.Kind) or all."""
    rules = NamingRule.objects.filter(enabled=True)
    if kind is not None:
        rules = rules.filter(object_type=kind.key)
    return rules.prefetch_related(*NamingRule.CONDITION_FIELDS).order_by('priority', 'name')


def ordered_rules(rules=None):
    """
    Enabled rules in the order they are tried: lowest priority first; on the
    same priority, the rule with more kinds of conditions first (a rule for
    switches tagged "lab" before one for all switches); then by name.
    """
    rules = list(rules if rules is not None else rules_queryset())
    return sorted(rules, key=lambda rule: (rule.priority, -rule.specificity, rule.name))


def _with_ancestors(obj):
    """pk of `obj` and of each of its parents."""
    pks = set()
    seen = 0
    while obj is not None and seen < 50:
        pks.add(obj.pk)
        obj = getattr(obj, 'parent', None)
        seen += 1
    return pks


def related_object(device, name):
    """A foreign key of the device, or None (also when the id points nowhere)."""
    if getattr(device, f'{name}_id', None) is None:
        return None
    try:
        return getattr(device, name)
    except Exception:  # noqa: BLE001 - a dangling id on an unsaved instance
        return None


def object_tag_slugs(device):
    pending = getattr(device, '_m2m_values', None)
    if pending and 'tags' in pending:
        values = pending['tags'] or []
        slugs = set()
        pks = []
        for value in values:
            if hasattr(value, 'slug'):
                slugs.add(value.slug)
            else:
                pks.append(value)
        if pks:
            from extras.models import Tag

            slugs.update(Tag.objects.filter(pk__in=pks).values_list('slug', flat=True))
        return slugs
    if device.pk:
        return set(device.tags.values_list('slug', flat=True))
    return set()


#: Apps and models an advanced condition may not look into. Which rule names
#: an object shows on its form and in the rule preview, so a condition such as
#: journal_entries__created_by__password__startswith would let anyone who may
#: edit rules read a secret one character at a time. Blocked: users, tokens
#: and permissions (users, auth), data sources with their credentials and the
#: change log (core), content types (they lead to every other model) and
#: webhooks with their secrets.
_PRIVATE_APPS = {'auth', 'users', 'core', 'contenttypes', 'sessions'}
_PRIVATE_MODELS = {'extras.webhook', 'extras.eventrule'}


def _is_private(model):
    return model is not None and (
        model._meta.app_label in _PRIVATE_APPS or model._meta.label_lower in _PRIVATE_MODELS
    )


def _field(obj, step):
    """The model field `step` of `obj` that a condition may follow, or None."""
    meta = getattr(obj, '_meta', None)
    if meta is None or _is_private(type(obj)):
        return None
    try:
        field = meta.get_field(step)
    except FieldDoesNotExist:
        return None
    return None if _is_private(field.related_model) else field


def _walk(value, path):
    """The values at `path` (field names) from `value`, or None for a path that can't be followed."""
    values = [value]
    for step in path:
        nxt = []
        for v in values:
            if v is None:
                continue
            if _field(v, step) is None:
                return None
            try:
                got = getattr(v, step)
            except Exception:  # noqa: BLE001 - a dangling id on an unsaved instance
                return None
            if isinstance(got, Manager):
                try:
                    nxt.extend(got.all())
                except ValueError:  # a reverse relation of an unsaved device
                    pass
            elif isinstance(got, (list, tuple, set)):
                nxt.extend(got)
            else:
                nxt.append(got)
        values = nxt
    return values


def constraint_errors(constraint, kind=DEVICE):
    """
    Keys of an advanced condition that name no field of the kind's model, or
    reach private data (see _PRIVATE_APPS), for the rule form.
    """
    filters = constraint if isinstance(constraint, list) else [constraint]
    errors = []
    for one in filters:
        if not isinstance(one, dict):
            errors.append(f'{one!r} is not an object such as {{"serial__startswith": "FOC"}}.')
            continue
        for key in one:
            parts = _split(key)[0]
            if parts[0] in ('tags', 'custom_field_data'):
                continue
            model = kind.model
            for step in parts:
                if model is None:
                    break  # past a generic relation: checked when matching
                try:
                    field = model._meta.get_field(step)
                except FieldDoesNotExist:
                    errors.append(f'"{key}": {model._meta.verbose_name} has no field "{step}".')
                    break
                if _is_private(field.related_model):
                    private = field.related_model._meta.verbose_name_plural
                    errors.append(f'"{key}": {private} can\'t be used in a condition.')
                    break
                if not (field.is_relation or step == parts[-1]):
                    errors.append(f'"{key}": "{step}" is a value, not a related object.')
                    break
                model = field.related_model
    return errors


def _compare(actual, lookup, expected):
    if lookup == 'isnull':
        return (actual is None) == bool(expected)
    if actual is None:
        return False
    if hasattr(actual, '_meta'):
        # A related object compared directly ("site": 3): compare its pk.
        actual = actual.pk
    if lookup == 'exact':
        return actual == expected or str(actual) == str(expected)
    if lookup == 'in':
        return actual in expected or str(actual) in [str(e) for e in expected]
    text, other = str(actual), str(expected)
    if lookup == 'iexact':
        return text.lower() == other.lower()
    if lookup == 'contains':
        return other in text
    if lookup == 'icontains':
        return other.lower() in text.lower()
    if lookup == 'startswith':
        return text.startswith(other)
    if lookup == 'istartswith':
        return text.lower().startswith(other.lower())
    if lookup == 'endswith':
        return text.endswith(other)
    if lookup == 'iendswith':
        return text.lower().endswith(other.lower())
    try:
        if lookup == 'gt':
            return actual > expected
        if lookup == 'gte':
            return actual >= expected
        if lookup == 'lt':
            return actual < expected
        if lookup == 'lte':
            return actual <= expected
    except TypeError:
        return False
    return False


def constraint_matches(constraint, device):
    """
    The advanced condition, evaluated on the instance (see change-approval's
    matching.py for the same idea). A list is OR'd, the keys of one dict are
    AND'ed. Supports the common lookups; `role__slug`, `site__name`,
    `tags__slug`, `custom_field_data__code` and so on.
    """
    if not constraint:
        return True
    filters = constraint if isinstance(constraint, list) else [constraint]
    for one in filters:
        if not isinstance(one, dict):
            continue
        if all(_term_matches(device, key, expected) for key, expected in one.items()):
            return True
    return False


def _split(key):
    """"site__name__iexact" -> (['site', 'name'], 'iexact')."""
    parts = key.split('__')
    if len(parts) > 1 and parts[-1] in _LOOKUPS:
        return parts[:-1], parts[-1]
    return parts, 'exact'


def _term_matches(device, key, expected):
    parts, lookup = _split(key)
    if parts[0] == 'tags':
        slugs = object_tag_slugs(device)
        field = parts[1] if len(parts) > 1 else 'slug'
        if field not in ('slug', 'name'):
            return False
        if field == 'name':
            from extras.models import Tag

            slugs = set(Tag.objects.filter(slug__in=slugs).values_list('name', flat=True))
        if not slugs:
            return lookup == 'isnull' and bool(expected)
        return any(_compare(s, lookup, expected) for s in slugs)
    if parts[0] == 'custom_field_data' and len(parts) == 2:
        return _compare((device.custom_field_data or {}).get(parts[1]), lookup, expected)
    values = _walk(device, parts)
    if values is None:
        return False
    if not values:
        return _compare(None, lookup, expected)
    return any(_compare(v, lookup, expected) for v in values)


def _condition_matches(condition, pks, obj):
    """Whether `obj`'s value at condition.path is one of `pks` (or a child of one)."""
    value = obj
    for step in condition.path:
        value = related_object(value, step)
        if value is None:
            return False
    found = _with_ancestors(value) if condition.tree else {value.pk}
    return bool(found & pks)


def rule_matches(rule, obj, tag_slugs=None):
    kind = rule.kind
    if not rule.enabled or kind_of(obj) is not kind:
        return False
    if kind.required_conditions and not any(getattr(rule, name).all() for name in kind.required_conditions):
        # A device rule must say what kind of device it is for.
        return False
    for condition in kind.conditions:
        pks = {related.pk for related in getattr(rule, condition.field).all()}
        if pks and not _condition_matches(condition, pks, obj):
            return False
    if rule.statuses and obj.status not in rule.statuses:
        return False

    wanted = {t.slug for t in rule.match_tags.all()}
    if wanted:
        have = object_tag_slugs(obj) if tag_slugs is None else tag_slugs
        if rule.tag_match == TagMatchChoices.ANY:
            if not wanted & have:
                return False
        elif not wanted <= have:
            return False

    return constraint_matches(rule.constraint, obj)


def find_rule(obj, rules=None, tag_slugs=None):
    """
    The first enabled rule for `obj`'s kind that matches it (see
    ordered_rules()), or None. `tag_slugs` saves a query per object when the
    caller has the tags already.
    """
    kind = kind_of(obj)
    if kind is None:
        return None
    prepare(obj)
    for rule in ordered_rules(rules if rules is not None else rules_queryset(kind)):
        if rule.kind is not kind:
            continue
        if rule.match_tags.all() and tag_slugs is None:
            tag_slugs = object_tag_slugs(obj)
        if rule_matches(rule, obj, tag_slugs=tag_slugs):
            return rule
    return None


def _expand_tree(model, pks):
    """pks plus every descendant of them, in one query (works for any nesting backend)."""
    children = {}
    for pk, parent in model.objects.values_list('pk', 'parent_id'):
        children.setdefault(parent, []).append(pk)
    out = set()
    todo = list(pks)
    while todo:
        pk = todo.pop()
        if pk not in out:
            out.add(pk)
            todo.extend(children.get(pk, ()))
    return out


def rule_objects(rule, limit=None, objects=None):
    """
    Objects this rule names: those of its kind it matches and no rule before
    it does. The database narrows them down by the simple conditions; the
    rest (tags "all", advanced condition, priority) is checked per object.
    `rule` may be an unsaved draft (preview.py); it takes the place of its
    saved version when rules are compared. `objects` narrows the objects
    looked at (by default all of the kind).
    """
    kind = rule.kind
    if kind.required_conditions and not any(getattr(rule, name).exists() for name in kind.required_conditions):
        return []
    if objects is None:
        objects = kind.model.objects.all()
    related = set()
    for condition in kind.conditions:
        wanted = {obj.pk for obj in getattr(rule, condition.field).all()}
        if not wanted:
            continue
        if condition.tree:
            wanted = _expand_tree(rule._meta.get_field(condition.field).related_model, wanted)
        objects = objects.filter(**{'__'.join(condition.path) + '__in': wanted})
    for root in kind.roots.values():
        if root:
            related.add('__'.join(root))
    if kind.has_primary_ip:
        related.update(('primary_ip4', 'primary_ip6'))
    if rule.statuses:
        objects = objects.filter(status__in=rule.statuses)
    objects = objects.select_related(*related).prefetch_related('tags').order_by('name', 'pk')
    rules = ordered_rules([r for r in rules_queryset(kind) if r.pk != rule.pk] + [rule])
    out = []
    for obj in objects.iterator(chunk_size=500):
        slugs = {t.slug for t in obj.tags.all()}
        if not rule_matches(rule, obj, tag_slugs=slugs):
            continue
        first = next((r for r in rules if rule_matches(r, obj, tag_slugs=slugs)), None)
        if first is not rule:
            continue
        out.append(obj)
        if limit and len(out) >= limit:
            break
    return out
