"""
Which rule names a device.

Matching works on the device as it is in memory, because a device being
created has no database row yet: its role, site, rack and so on are read from
the instance, its tags from what the form or the API is about to save
(`instance._m2m_values['tags']`, set by NetBox before validation) or, for a
saved device without such values, from the database.

Rules are checked by priority (then name); the first enabled rule whose
conditions all match wins. Within a condition any listed value matches. Roles,
regions and locations match their children too.
"""
from django.core.exceptions import FieldDoesNotExist
from django.db.models import Manager

from .models import NamingRule, TagMatchChoices

__all__ = ('find_rule', 'rule_matches', 'device_tag_slugs', 'rules_queryset', 'ordered_rules')

_LOOKUPS = {
    'exact', 'iexact', 'in', 'isnull', 'gt', 'gte', 'lt', 'lte',
    'contains', 'icontains', 'startswith', 'istartswith', 'endswith', 'iendswith',
}


def rules_queryset():
    return NamingRule.objects.filter(enabled=True).prefetch_related(
        'roles', 'device_types', 'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms',
        'match_tags',
    ).order_by('priority', 'name')


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


def _related(device, name):
    """A foreign key of the device, or None (also when the id points nowhere)."""
    if getattr(device, f'{name}_id', None) is None:
        return None
    try:
        return getattr(device, name)
    except Exception:  # noqa: BLE001 - a dangling id on an unsaved instance
        return None


def device_tag_slugs(device):
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


#: Models an advanced condition may not look into: users (their passwords),
#: their API tokens and preferences. Which rule names a device shows on every
#: device form, so a condition such as
#: journal_entries__created_by__password__startswith would let anyone who may
#: edit rules read a password hash one character at a time.
_PRIVATE_MODELS = {'users.user', 'users.token', 'users.userconfig'}


def _is_private(model):
    return model is not None and (
        model._meta.label_lower in _PRIVATE_MODELS or model._meta.app_label == 'auth'
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


def constraint_errors(constraint):
    """
    Keys of an advanced condition that name no field of a device, or reach
    users (see _PRIVATE_MODELS), for the rule form.
    """
    from dcim.models import Device

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
            model = Device
            for step in parts:
                if model is None:
                    break  # past a generic relation: checked when matching
                try:
                    field = model._meta.get_field(step)
                except FieldDoesNotExist:
                    errors.append(f'"{key}": {model._meta.verbose_name} has no field "{step}".')
                    break
                if _is_private(field.related_model):
                    errors.append(f'"{key}": users and their tokens can\'t be used in a condition.')
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
        slugs = device_tag_slugs(device)
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


def rule_matches(rule, device, tag_slugs=None):
    if not rule.enabled:
        return False

    role = _related(device, 'role')
    roles = {r.pk for r in rule.roles.all()}
    types = {t.pk for t in rule.device_types.all()}
    if not roles and not types:
        # A rule must say what kind of device it is for.
        return False
    if roles and not (role and _with_ancestors(role) & roles):
        return False
    if types and device.device_type_id not in types:
        return False

    site = _related(device, 'site')
    sites = {s.pk for s in rule.sites.all()}
    if sites and device.site_id not in sites:
        return False
    regions = {r.pk for r in rule.regions.all()}
    if regions and not (site and site.region_id and _with_ancestors(site.region) & regions):
        return False
    groups = {g.pk for g in rule.site_groups.all()}
    if groups and not (site and site.group_id and _with_ancestors(site.group) & groups):
        return False
    locations = {loc.pk for loc in rule.locations.all()}
    if locations:
        location = _related(device, 'location')
        if not (location and _with_ancestors(location) & locations):
            return False
    tenants = {t.pk for t in rule.tenants.all()}
    if tenants and device.tenant_id not in tenants:
        return False
    platforms = {p.pk for p in rule.platforms.all()}
    if platforms and device.platform_id not in platforms:
        return False
    if rule.statuses and device.status not in rule.statuses:
        return False

    wanted = {t.slug for t in rule.match_tags.all()}
    if wanted:
        have = device_tag_slugs(device) if tag_slugs is None else tag_slugs
        if rule.tag_match == TagMatchChoices.ANY:
            if not wanted & have:
                return False
        elif not wanted <= have:
            return False

    return constraint_matches(rule.constraint, device)


def find_rule(device, rules=None):
    """The first enabled rule that matches `device` (see ordered_rules()), or None."""
    tag_slugs = None
    for rule in ordered_rules(rules):
        if rule.match_tags.all() and tag_slugs is None:
            tag_slugs = device_tag_slugs(device)
        if rule_matches(rule, device, tag_slugs=tag_slugs):
            return rule
    return None


def _expand_tree(model, pks):
    """pks plus every descendant of them (works for any nesting backend)."""
    if not pks:
        return set()
    out = set()
    for obj in model.objects.all():
        if _with_ancestors(obj) & pks:
            out.add(obj.pk)
    return out


def rule_devices(rule, limit=None, devices=None):
    """
    Devices this rule names: those it matches and no rule before it does.
    The database narrows them down by the simple conditions; the rest
    (tags "all", advanced condition, priority) is checked per device.
    `rule` may be an unsaved draft (preview.py); it takes the place of its
    saved version when rules are compared. `devices` narrows the devices
    looked at (by default all).
    """
    from dcim.models import Device, DeviceRole, Location, Region

    roles = _expand_tree(DeviceRole, {r.pk for r in rule.roles.all()})
    types = {t.pk for t in rule.device_types.all()}
    if not roles and not types:
        return []
    if devices is None:
        devices = Device.objects.all()
    if roles:
        devices = devices.filter(role_id__in=roles)
    if types:
        devices = devices.filter(device_type_id__in=types)
    if rule.sites.exists():
        devices = devices.filter(site__in=rule.sites.all())
    regions = _expand_tree(Region, {r.pk for r in rule.regions.all()})
    if regions:
        devices = devices.filter(site__region_id__in=regions)
    locations = _expand_tree(Location, {loc.pk for loc in rule.locations.all()})
    if locations:
        devices = devices.filter(location_id__in=locations)
    if rule.tenants.exists():
        devices = devices.filter(tenant__in=rule.tenants.all())
    if rule.platforms.exists():
        devices = devices.filter(platform__in=rule.platforms.all())
    if rule.statuses:
        devices = devices.filter(status__in=rule.statuses)
    devices = devices.select_related(
        'site', 'site__region', 'site__group', 'location', 'rack', 'role', 'device_type',
        'device_type__manufacturer', 'tenant', 'platform', 'primary_ip4', 'primary_ip6',
    ).prefetch_related('tags').order_by('name', 'pk')
    rules = ordered_rules([r for r in rules_queryset() if r.pk != rule.pk] + [rule])
    out = []
    for device in devices.iterator(chunk_size=500):
        slugs = {t.slug for t in device.tags.all()}
        if not rule_matches(rule, device, tag_slugs=slugs):
            continue
        first = next((r for r in rules if rule_matches(r, device, tag_slugs=slugs)), None)
        if first is not rule:
            continue
        out.append(device)
        if limit and len(out) >= limit:
            break
    return out
