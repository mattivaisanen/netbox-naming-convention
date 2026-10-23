"""
Names for devices: what the rule suggests, and taking a number for real.

- `suggest()` works out the name a device would get, without saving or
  reserving anything (the device form, the API's suggest endpoint, the
  device panel).
- `assign()` does it for real while the series row is locked, inside the
  save's transaction, so two devices saved at the same time never get the
  same number. signals.py calls it.
- `check_typed_name()` is the "refuse" enforcement for names people type.
- `follows()` tells whether a device's name fits its rule (device panel,
  the rule's list of devices that don't).
"""
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

from django.db import transaction
from django.utils.translation import gettext as _

from netbox.context import current_request

from .matching import _related, find_rule
from .models import AssignedName, NamingSeries, NumberSourceChoices
from .numbering import (
    NumberError, is_skipped, name_regex, next_number, number_from_ip, series_key, used_numbers,
)
from .template import NUMBER, ROOTS, TemplateError

__all__ = ('Suggestion', 'suggest', 'assign', 'check_typed_name', 'follows', 'resolve', 'mark_auto', 'is_auto')

#: Longest name NetBox accepts for a device.
MAX_NAME = 64


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
    #: The device keeps the number it has (only when editing).
    kept_number: bool = False
    #: The rule's name for this device with ### for the number, such as
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


def resolve(device, path):
    """The value of a template path (see template.py) for `device`, or ''."""
    root, *rest = path
    obj = device
    for step in ROOTS[root]:
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


def _primary_ip(device):
    return _related(device, 'primary_ip4') or _related(device, 'primary_ip6')


def _render(device, rule):
    """(Suggestion with prefix/suffix/series/missing filled in, has_number)."""
    out = Suggestion(rule=rule)
    try:
        template = rule.parsed_template
    except TemplateError as e:
        out.error = _('The rule "{rule}" has a broken template: {error}').format(rule=rule, error=e)
        return out, False
    rendered = template.render(lambda path: resolve(device, path))
    out.prefix, out.suffix, out.missing = rendered.prefix, rendered.suffix, list(rendered.missing)
    out.pattern = rendered.pattern.replace(NUMBER, '#' * rule.number_digits)
    if template.has_number:
        out.series = series_key(out.prefix, out.suffix, rule.number_scope)
    if template.has_number and rule.number_source == NumberSourceChoices.IP and _primary_ip(device) is None:
        out.missing.append('primary IP')
    return out, template.has_number


def _number_of(name, prefix, suffix, scope):
    """The number in an existing name of this series, or None."""
    if not name:
        return None
    match = re.match(name_regex(prefix, suffix, scope), name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _finish(out, rule, number):
    out.number = number
    name = out.prefix + rule.format_number(number) + out.suffix
    if len(name) > MAX_NAME:
        out.error = _('The name {name} is longer than {n} characters.').format(name=name, n=MAX_NAME)
        return out
    out.name = name
    return out


def _pick(out, rule, device, high_water, keep_current, taken=None):
    """Choose the number for a rendered suggestion."""
    scope = rule.number_scope
    used = used_numbers(out.prefix, out.suffix, scope, exclude_pk=device.pk)
    if taken:
        used = set(used) | taken.get(out.series, set())
    if rule.number_source == NumberSourceChoices.IP:
        ip = _primary_ip(device)
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
            out.error = _('Number {number} of {series} is already used by another device.').format(
                number=rule.format_number(number), series=out.prefix,
            )
            return out
        return _finish(out, rule, number)

    if keep_current and device.pk:
        # Editing: a device that stays in its series keeps its number. One
        # whose name drifted (renamed by hand) gets back the number a rule
        # gave it, while nobody else has it.
        earlier = AssignedName.objects.filter(device_id=device.pk).exclude(name=device.name or '')
        for name in [device.name, *earlier.values_list('name', flat=True)]:
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


def suggest(device, rule=None, *, keep_current=True, taken=None):
    """
    The name `device` would get now. Saves and reserves nothing. `taken`
    ({series: {numbers}}) are numbers to treat as used, for suggesting names
    for several devices at once.
    """
    rule = rule or find_rule(device)
    if rule is None:
        return Suggestion()
    out, has_number = _render(device, rule)
    if out.error or out.missing:
        return out
    if not has_number:
        out.name = out.prefix
        if len(out.name) > MAX_NAME:
            out.error = _('The name {name} is longer than {n} characters.').format(name=out.name, n=MAX_NAME)
            out.name = None
        return out
    high_water = NamingSeries.objects.filter(key=out.series).values_list('high_water', flat=True).first() or 0
    return _pick(out, rule, device, high_water, keep_current, taken)


def assign(device, rule=None):
    """
    Give `device` its name for real: lock the series, pick the number again
    (someone may have taken the suggested one) and remember it as handed out.
    Returns the Suggestion; `device.name` is set when it is ready.

    Inside a transaction (NetBox's views, API and CSV import all save in one)
    the lock is held until that transaction ends. Outside one it covers the
    choice only.
    """
    rule = rule or find_rule(device)
    if rule is None:
        return Suggestion()
    out, has_number = _render(device, rule)
    if out.error or out.missing:
        return out
    if not has_number:
        out = suggest(device, rule)
        if out.ready:
            device.name = out.name
        return out
    with transaction.atomic():
        NamingSeries.objects.bulk_create([NamingSeries(key=out.series)], ignore_conflicts=True)
        series = NamingSeries.objects.select_for_update().get(key=out.series)
        out = _pick(out, rule, device, series.high_water, keep_current=False)
        if out.ready:
            device.name = out.name
            if out.number > series.high_water:
                series.high_water = out.number
                series.save(update_fields=('high_water', 'last_updated'))
    return out


def remember(device, rule=None):
    """
    A device saved with a name it was given by hand: if the name belongs to
    its rule's series, remember the number as handed out (so it does not
    come back after the device is deleted, when gap filling is off).
    """
    rule = rule or find_rule(device)
    if rule is None or rule.number_source != NumberSourceChoices.SEQUENCE:
        return
    out, has_number = _render(device, rule)
    if not has_number or out.error or out.missing:
        return
    number = _number_of(device.name, out.prefix, out.suffix, rule.number_scope)
    if number is None:
        return
    NamingSeries.objects.bulk_create([NamingSeries(key=out.series)], ignore_conflicts=True)
    NamingSeries.objects.filter(key=out.series, high_water__lt=number).update(high_water=number)


def follows(device, rule=None):
    """(rule, True/False) whether the device's name fits its rule; (None, None) without a rule."""
    rule = rule or find_rule(device)
    if rule is None:
        return None, None
    out, has_number = _render(device, rule)
    if out.error:
        return rule, False
    if out.missing and out.missing != ['primary IP']:
        return rule, False
    name = device.name or ''
    if not has_number:
        return rule, name.lower() == out.prefix.lower()
    number = _number_of(name, out.prefix, out.suffix, 'name')
    if number is None or len(name) - len(out.prefix) - len(out.suffix) < rule.number_digits:
        return rule, False
    if rule.number_source == NumberSourceChoices.IP:
        ip = _primary_ip(device)
        try:
            return rule, ip is not None and number_from_ip(rule.ip_pattern, ip.address) == number
        except NumberError:
            return rule, False
    return rule, rule.number_first <= number <= rule.last_number


def check_typed_name(device, rule):
    """
    For rules that refuse names that don't fit: an error message for a name
    typed by hand, or None when it is fine.
    """
    out, has_number = _render(device, rule)
    if out.error:
        return out.error
    if out.missing and out.missing != ['primary IP']:
        return _('The rule "{rule}" needs a value for: {missing}.').format(rule=rule, missing=', '.join(out.missing))
    _rule, fits = follows(device, rule)
    example = suggest(device, rule)
    if not fits:
        hint = _(' Leave the name empty to get {name}.').format(name=example.name) if example.ready else ''
        return _('The name does not follow the rule "{rule}".').format(rule=rule) + hint
    if has_number:
        number = _number_of(device.name, out.prefix, out.suffix, 'name')
        if is_skipped(number, rule.skip_ranges):
            return _('Number {number} is never handed out by the rule "{rule}".').format(
                number=rule.format_number(number), rule=rule,
            )
        if number in used_numbers(out.prefix, out.suffix, rule.number_scope, exclude_pk=device.pk):
            return _('Number {number} of {series} is already used by another device.').format(
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


def mark_auto(device):
    device._naming_auto = True
    if device.name:
        _auto_set().add(device.name)


def is_auto(device):
    if getattr(device, '_naming_auto', False):
        return True
    return bool(device.name) and device._state.adding and device.name in _auto_set()


def unmark_auto(device):
    device._naming_auto = False
    _auto_set().discard(device.name)
