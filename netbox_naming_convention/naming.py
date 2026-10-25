"""
Names for objects (devices, virtual machines, racks): what the rule
suggests, and taking a number for real.

- `suggest()` works out the name an object would get, without saving or
  reserving anything (the object forms, the API's suggest endpoint, the
  naming panel).
- `assign()` does it for real while the series row is locked, inside the
  save's transaction, so two objects saved at the same time never get the
  same number. signals.py calls it.
- `check_typed_name()` is the "refuse" enforcement for names people type.
- `follows()` tells whether an object's name fits its rule (naming panel,
  the rule's list of objects that don't).
- `reserve()` takes names ahead of time, before their objects exist. Their
  numbers count as used until the reservation is used up or expires.
"""
import re
from contextvars import ContextVar
from dataclasses import dataclass, field, replace

from django.db import transaction
from django.utils.translation import gettext as _

from netbox.context import current_request

from .kinds import prepare
from .matching import _related, find_rule
from .models import AssignedName, NamingSeries, NumberSourceChoices, ReservedName
from .numbering import (
    NumberError, is_skipped, name_regex, next_number, number_from_ip, series_key, used_numbers,
)
from .template import NUMBER, TemplateError, filter_name

__all__ = (
    'Suggestion', 'suggest', 'assign', 'reserve', 'check_typed_name', 'follows', 'resolve', 'mark_auto', 'is_auto',
)

@dataclass
class Suggestion:
    rule: object = None
    name: str = None
    number: int = None
    series: str = ''
    prefix: str = ''
    suffix: str = ''
    #: Values the name waits for ("rack", "primary IP").
    missing: list = field(default_factory=list)
    error: str = None
    #: The object keeps the number it has (only when editing).
    kept_number: bool = False
    #: The rule's name for this object with ### for the number, such as
    #: AMS1-SW###-<rack> (see Rendered.pattern).
    pattern: str = ''

    @property
    def ready(self):
        return bool(self.name) and not self.missing and not self.error

    def as_dict(self):
        return {
            'rule': {'id': self.rule.pk, 'name': self.rule.name, 'enforcement': self.rule.enforcement}
            if self.rule else None,
            'name': self.name if self.ready else None,
            'number': self.number if self.ready else None,
            'series': self.series or None,
            'missing': self.missing,
            'error': self.error,
            'ready': self.ready,
            'kept_number': self.kept_number,
            'pattern': self.pattern or None,
        }


def resolve(obj, path, kind):
    """The value of a template path (see template.py) for `obj` of `kind`, or ''."""
    root, *rest = path
    for step in kind.roots[root]:
        obj = _related(obj, step)
        if obj is None:
            return ''
    i = 0
    while i < len(rest):
        step = rest[i]
        if step == 'parent':
            obj = getattr(obj, 'parent', None)
            if obj is None:
                return ''
        elif step == 'cf':
            value = (getattr(obj, 'custom_field_data', None) or {}).get(rest[i + 1])
            return '' if value is None else str(value)
        else:
            value = getattr(obj, step, '')
            return '' if value is None else str(value)
        i += 1
    return ''


def _primary_ip(obj):
    return _related(obj, 'primary_ip4') or _related(obj, 'primary_ip6')


def _has_value(obj, key):
    """Whether a field the rule waits for (RequiredValueChoices) is set."""
    if obj._meta.get_field(key).is_relation:
        return _related(obj, key) is not None
    return bool(getattr(obj, key, None))


def _render(obj, rule, waits=True):
    """
    (Suggestion with prefix/suffix/series/missing filled in, has_number).
    `waits=False` leaves out the rule's *Wait for* fields (reserving names
    for objects to come needs only what the template uses).
    """
    out = Suggestion(rule=rule)
    try:
        template = rule.parsed_template
    except TemplateError as e:
        out.error = _('The rule "{rule}" has a broken template: {error}').format(rule=rule, error=e)
        return out, False
    kind = rule.kind
    prepare(obj)
    rendered = template.render(lambda path: resolve(obj, path, kind))
    filters = rule.parsed_name_filters
    out.prefix = filter_name(rendered.prefix, filters)
    out.suffix = filter_name(rendered.suffix, filters)
    # Fields the rule waits for, in the rule's order, before the template's own.
    waiting = [key for key in rule.required_values if key in kind.wait_for and not _has_value(obj, key)] if waits else []
    out.missing = waiting + [m for m in rendered.missing if m not in waiting]
    out.pattern = filter_name(rendered.pattern, filters).replace(NUMBER, '#' * rule.number_digits)
    if template.has_number:
        out.series = series_key(out.prefix, out.suffix, rule.number_scope, kind.key)
    if template.has_number and rule.number_source == NumberSourceChoices.IP and _primary_ip(obj) is None:
        out.missing.append('primary IP')
    return out, template.has_number


def _number_of(name, prefix, suffix, scope):
    """The number in an existing name of this series, or None."""
    if not name:
        return None
    match = re.match(name_regex(prefix, suffix, scope), name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _too_long(name, rule):
    if len(name) <= rule.kind.max_name:
        return None
    return _('The name {name} is longer than {n} characters.').format(name=name, n=rule.kind.max_name)


def _taken(rule, number, series):
    return _('Number {number} of {series} is already used by another {kind}.').format(
        number=rule.format_number(number), series=series, kind=rule.kind.label.lower(),
    )


def _reserved(series, name=None):
    """Numbers of the series' active reservations, except the one for `name` (an object may use its own)."""
    if not series:
        return set()
    rows = ReservedName.objects.active().filter(series=series, number__isnull=False)
    if name:
        rows = rows.exclude(name__iexact=name)
    return set(rows.values_list('number', flat=True))


def _finish(out, rule, number):
    out.number = number
    name = out.prefix + rule.format_number(number) + out.suffix
    out.error = _too_long(name, rule)
    if out.error is None:
        out.name = name
    return out


def _pick(out, rule, obj, high_water, keep_current, taken=None):
    """Choose the number for a rendered suggestion."""
    scope = rule.number_scope
    used = used_numbers(out.prefix, out.suffix, scope, rule.kind.model, exclude_pk=obj.pk)
    used = set(used) | _reserved(out.series, obj.name)
    if taken:
        used = set(used) | taken.get(out.series, set())
    if rule.number_source == NumberSourceChoices.IP:
        ip = _primary_ip(obj)
        try:
            number = number_from_ip(rule.ip_pattern, ip.address)
        except NumberError as e:
            out.error = str(e)
            return out
        if number is None:
            out.error = _('The primary IP {ip} does not match the rule\'s IP pattern {pattern}.').format(
                ip=ip, pattern=rule.ip_pattern,
            )
            return out
        if number in used:
            out.error = _taken(rule, number, out.prefix)
            return out
        return _finish(out, rule, number)

    if keep_current and obj.pk:
        # Editing: an object that stays in its series keeps its number. One
        # whose name drifted (renamed by hand) gets back the number a rule
        # gave it, while nobody else has it.
        earlier = AssignedName.of(obj).exclude(name=obj.name or '')
        for name in [obj.name, *earlier.values_list('name', flat=True)]:
            current = _number_of(name, out.prefix, out.suffix, scope)
            if (current is not None and current not in used and rule.number_first <= current <= rule.last_number
                    and not is_skipped(current, rule.skip_ranges)):
                out.kept_number = True
                return _finish(out, rule, current)
    try:
        number = next_number(
            used, first=rule.number_first, last=rule.last_number, skip=rule.skip_ranges,
            fill_gaps=rule.fill_gaps, high_water=high_water,
        )
    except NumberError:
        out.error = _('The series {series} is full: no free numbers from {first} to {last}.').format(
            series=out.prefix or out.series, first=rule.format_number(rule.number_first),
            last=rule.format_number(rule.last_number),
        )
        return out
    return _finish(out, rule, number)


def suggest(obj, rule=None, *, keep_current=True, taken=None):
    """
    The name `obj` would get now. Saves and reserves nothing. `taken`
    ({series: {numbers}}) are numbers to treat as used, for suggesting names
    for several objects at once.
    """
    rule = rule or find_rule(obj)
    if rule is None:
        return Suggestion()
    out, has_number = _render(obj, rule)
    if out.error or out.missing:
        return out
    if not has_number:
        out.error = _too_long(out.prefix, rule)
        out.name = None if out.error else out.prefix
        return out
    high_water = NamingSeries.objects.filter(key=out.series).values_list('high_water', flat=True).first() or 0
    return _pick(out, rule, obj, high_water, keep_current, taken)


def assign(obj, rule=None):
    """
    Give `obj` its name for real: lock the series, pick the number again
    (someone may have taken the suggested one) and remember it as handed out.
    Returns the Suggestion; `obj.name` is set when it is ready.

    Inside a transaction (NetBox's views, API and CSV import all save in one)
    the lock is held until that transaction ends. Outside one it covers the
    choice only.
    """
    rule = rule or find_rule(obj)
    if rule is None:
        return Suggestion()
    out, has_number = _render(obj, rule)
    if out.error or out.missing:
        return out
    if not has_number:
        out = suggest(obj, rule)
        if out.ready:
            obj.name = out.name
        return out
    with transaction.atomic():
        NamingSeries.objects.bulk_create([NamingSeries(key=out.series)], ignore_conflicts=True)
        series = NamingSeries.objects.select_for_update().get(key=out.series)
        out = _pick(out, rule, obj, series.high_water, keep_current=False)
        if out.ready:
            obj.name = out.name
            if out.number > series.high_water:
                series.high_water = out.number
                series.save(update_fields=('high_water', 'last_updated'))
    return out


#: Most names reserved in one go.
RESERVE_LIMIT = 100


def reserve(obj, rule, count=1, *, expires=None, description='', user=None):
    """
    Reserve the next `count` names `rule` gives an object like `obj` (an
    unsaved object carrying the values the name is built from, such as its
    site and rack). Takes the numbers under the series lock, like assign().
    Returns (reservations, error); nothing is reserved on an error.
    """
    if rule.number_source == NumberSourceChoices.IP:
        return [], _('A rule that reads its number from the IP can\'t reserve names.')
    if not 1 <= count <= RESERVE_LIMIT:
        return [], _('Reserve from 1 to {n} names at a time.').format(n=RESERVE_LIMIT)
    out, has_number = _render(obj, rule, waits=False)
    if out.error:
        return [], out.error
    if out.missing:
        return [], _('The name needs a value for: {missing}.').format(missing=', '.join(out.missing))
    fields = {
        'object_type': rule.kind.key, 'rule': rule, 'expires': expires, 'description': description,
        'created_by': getattr(user, 'username', '') or '',
    }
    if not has_number:
        return _reserve_fixed(out, rule, count, fields)
    with transaction.atomic():
        NamingSeries.objects.bulk_create([NamingSeries(key=out.series)], ignore_conflicts=True)
        series = NamingSeries.objects.select_for_update().get(key=out.series)
        # An expired reservation gives its number back (with gap filling) and its name.
        ReservedName.objects.filter(series=out.series).exclude(pk__in=ReservedName.objects.active()).delete()
        taken, picked = {}, []
        for _i in range(count):
            hint = _pick(replace(out), rule, obj, series.high_water, keep_current=False, taken=taken)
            if not hint.ready:
                return [], hint.error
            taken.setdefault(out.series, set()).add(hint.number)
            picked.append(hint)
        reservations = ReservedName.objects.bulk_create([
            ReservedName(name=hint.name, series=out.series, number=hint.number, **fields) for hint in picked
        ])
        highest = max(hint.number for hint in picked)
        if highest > series.high_water:
            series.high_water = highest
            series.save(update_fields=('high_water', 'last_updated'))
    return reservations, None


def _reserve_fixed(out, rule, count, fields):
    """A rule without {n} gives one name: reserve it when nobody has it."""
    name = out.prefix
    if count != 1:
        return [], _('The rule gives only one name (its template has no {n}).')
    if error := _too_long(name, rule):
        return [], error
    model = rule.kind.model
    if model.objects.filter(name__iexact=name).exists():
        return [], _('A {kind} named {name} exists already.').format(kind=rule.kind.label.lower(), name=name)
    ReservedName.objects.filter(object_type=rule.kind.key, name__iexact=name).exclude(
        pk__in=ReservedName.objects.active(),
    ).delete()
    if ReservedName.objects.filter(object_type=rule.kind.key, name__iexact=name).exists():
        return [], _('{name} is reserved already.').format(name=name)
    return [ReservedName.objects.create(name=name, **fields)], None


def remember(obj, rule=None):
    """
    An object saved with a name it was given by hand: if the name belongs to
    its rule's series, remember the number as handed out (so it does not
    come back after the object is deleted, when gap filling is off).
    """
    rule = rule or find_rule(obj)
    if rule is None or rule.number_source != NumberSourceChoices.SEQUENCE:
        return
    out, has_number = _render(obj, rule)
    if not has_number or out.error or out.missing:
        return
    number = _number_of(obj.name, out.prefix, out.suffix, rule.number_scope)
    # A number outside the rule's range was never the rule's to hand out (and
    # may not even fit the database column, as in SW99999999999).
    if number is None or not rule.number_first <= number <= rule.last_number:
        return
    NamingSeries.objects.bulk_create([NamingSeries(key=out.series)], ignore_conflicts=True)
    NamingSeries.objects.filter(key=out.series, high_water__lt=number).update(high_water=number)


def follows(obj, rule=None):
    """(rule, True/False) whether the object's name fits its rule; (None, None) without a rule."""
    rule = rule or find_rule(obj)
    if rule is None:
        return None, None
    out, has_number = _render(obj, rule)
    if out.error:
        return rule, False
    if out.missing and out.missing != ['primary IP']:
        return rule, False
    name = obj.name or ''
    if not has_number:
        return rule, name.lower() == out.prefix.lower()
    number = _number_of(name, out.prefix, out.suffix, 'name')
    if number is None or len(name) - len(out.prefix) - len(out.suffix) < rule.number_digits:
        return rule, False
    if rule.number_source == NumberSourceChoices.IP:
        ip = _primary_ip(obj)
        try:
            return rule, ip is not None and number_from_ip(rule.ip_pattern, ip.address) == number
        except NumberError:
            return rule, False
    return rule, rule.number_first <= number <= rule.last_number


def check_typed_name(obj, rule):
    """
    For rules that refuse names that don't fit: an error message for a name
    typed by hand, or None when it is fine.
    """
    out, has_number = _render(obj, rule)
    if out.error:
        return out.error
    if out.missing and out.missing != ['primary IP']:
        return _('The rule "{rule}" needs a value for: {missing}.').format(rule=rule, missing=', '.join(out.missing))
    _rule, fits = follows(obj, rule)
    example = suggest(obj, rule)
    if not fits:
        hint = _(' Leave the name empty to get {name}.').format(name=example.name) if example.ready else ''
        return _('The name does not follow the rule "{rule}".').format(rule=rule) + hint
    if has_number:
        number = _number_of(obj.name, out.prefix, out.suffix, 'name')
        if is_skipped(number, rule.skip_ranges):
            return _('Number {number} is never handed out by the rule "{rule}".').format(
                number=rule.format_number(number), rule=rule,
            )
        if number in used_numbers(out.prefix, out.suffix, rule.number_scope, rule.kind.model, exclude_pk=obj.pk):
            return _taken(rule, number, out.prefix)
        if number in _reserved(out.series, obj.name):
            return _('Number {number} of {series} is reserved for another name.').format(
                number=rule.format_number(number), series=out.prefix,
            )
    return None


#
# Names the plugin filled in during validation, to be picked again under the
# lock at save time. The form path keeps the instance (instance._naming_auto);
# the REST API validates a copy, so it remembers the name for the request.
#

_auto_names = ContextVar('naming_auto_names', default=None)


def _auto_set():
    request = current_request.get()
    if request is not None:
        names = getattr(request, '_naming_auto_names', None)
        if names is None:
            names = set()
            request._naming_auto_names = names
        return names
    names = _auto_names.get()
    if names is None:
        names = set()
        _auto_names.set(names)
    return names


def mark_auto(obj):
    obj._naming_auto = True
    if obj.name:
        _auto_set().add(obj.name)


def is_auto(obj):
    if getattr(obj, '_naming_auto', False):
        return True
    return bool(obj.name) and obj._state.adding and obj.name in _auto_set()


def unmark_auto(obj):
    obj._naming_auto = False
    _auto_set().discard(obj.name)
