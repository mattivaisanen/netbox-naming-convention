"""
Name templates.

A template is literal text with parts in braces:

- ``{n}``: the number (padded to the rule's digits). At most one.
- ``{a-z}`` or ``{A-Z}``: the number as one letter instead (a is 1, z is
  26), lower or upper case. A template has one counter at most: {n}, {a-z}
  or {A-Z}.
- ``{path|filter|filter}``: a value of the object, such as ``{site.name}``,
  ``{role.parent.slug}``, ``{rack.name}`` or ``{site.cf.code}``, changed by
  filters from left to right. Where a path may start depends on the kind of
  object the rule names (`kinds.Kind.roots`).

``{{`` and ``}}`` are literal braces. Everything else is literal text, so
``SW{n}`` is a valid template with no values at all.

The text before the counter is the *prefix*, the text after it the *suffix*. A
rule's series is its prefix (number scope "shared") or prefix + suffix
("whole name"); see numbering.py.

A value that is empty makes the name *wait* for it (the form shows "waiting
for: rack"), unless the part has ``|optional`` (left out) or ``|default:X``.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from .kinds import DEVICE

__all__ = (
    'Template', 'TemplateError', 'Rendered', 'ATTRIBUTES', 'FILTERS', 'NUMBER', 'COUNTERS', 'NAME_FILTERS',
    'parse_name_filters', 'filter_name',
)


class TemplateError(ValueError):
    pass


#: Attributes a path may read on any object it reaches (besides `parent`,
#: which goes one level up in a nested object such as a role or region, and
#: `cf.<name>` for a custom field). Kept short on purpose: names are built
#: from what identifies a place or a kind of device, never from secrets or
#: free text.
ATTRIBUTES = {'name', 'slug', 'model', 'part_number', 'facility', 'facility_id', 'serial', 'asset_tag', 'label'}

#: Filters and how many arguments each takes.
FILTERS = {
    'upper': 0,
    'lower': 0,
    'ascii': 0,
    'alnum': 0,
    'nospace': 0,
    'optional': 0,
    'first': 1,
    'last': 1,
    'default': 1,
    'before': 1,
    'after': 1,
    'replace': 2,
}

#: Stands for the number in Rendered.pattern.
NUMBER = '\x00'

#: The counters a template may have, and how each writes the number.
COUNTERS = {'n': 'digits', 'a-z': 'lower', 'A-Z': 'upper'}

_TOKEN = re.compile(r'\{\{|\}\}|\{([^{}]*)\}|[{}]')


@dataclass
class Part:
    kind: str  # 'text', 'number' or 'value'
    #: Literal text, or for a number part its counter (COUNTERS values).
    text: str = ''
    path: tuple = ()
    filters: list = field(default_factory=list)
    #: The root that is the object itself ("device"), left out of `source`.
    own_root: str = ''

    @property
    def optional(self):
        return any(name in ('optional', 'default') for name, _ in self.filters)

    @property
    def source(self):
        """What the part needs, for messages: "rack", "role.parent", "site.cf.code"."""
        path = list(self.path)
        if len(path) > 1 and path[-1] in ATTRIBUTES and path[-2] != 'cf':
            path.pop()
        if path and path[0] == self.own_root and len(path) > 1:
            path.pop(0)
        return '.'.join(path)


@dataclass
class Rendered:
    """A template filled in for one device."""
    prefix: str = ''
    suffix: str = ''
    has_number: bool = False
    #: Paths whose values are missing (the name waits for them).
    missing: list = field(default_factory=list)
    #: The name with NUMBER where the number goes and <rack> for a missing
    #: value: what the rule makes of this device, for messages.
    pattern: str = ''

    @property
    def ready(self):
        return not self.missing

    def name(self, number_text=''):
        return self.prefix + number_text + self.suffix if self.has_number else self.prefix


def _parse_filter(text):
    name, *args = text.split(':')
    name = name.strip()
    if name not in FILTERS:
        raise TemplateError(f'Unknown filter "{name}". Known filters: {", ".join(sorted(FILTERS))}.')
    wanted = FILTERS[name]
    if name == 'replace' and len(args) == 1:
        args.append('')
    if len(args) != wanted:
        raise TemplateError(f'Filter "{name}" takes {wanted} argument(s) ("{name}:..."), got {len(args)}.')
    if name in ('first', 'last'):
        try:
            count = int(args[0])
        except ValueError:
            raise TemplateError(f'Filter "{name}" needs a number, such as "{name}:2".') from None
        if count < 1:
            raise TemplateError(f'Filter "{name}" needs a number of at least 1.')
        args = [count]
    return name, args


def _parse_path(text, kind):
    parts = [p.strip() for p in text.split('.')]
    if not all(parts):
        raise TemplateError(f'"{text}" is not a valid value. Use for example {{site.name}} or {{site.slug}}.')
    root, rest = parts[0], parts[1:]
    if root == 'cf':
        # A custom field of the object itself.
        root, rest = kind.own_root, parts
    if root not in kind.roots:
        raise TemplateError(
            f'Unknown value "{root}". For {kind.label_plural} a value starts with one of: '
            f'{", ".join(sorted(kind.roots))}, or cf.'
        )
    i = 0
    while i < len(rest):
        step = rest[i]
        if step == 'parent':
            i += 1
            continue
        if step == 'cf':
            if i + 1 >= len(rest):
                raise TemplateError(f'"{text}": "cf" needs a custom field name after it, such as cf.code.')
            if i + 2 != len(rest):
                raise TemplateError(f'"{text}": a custom field must be the last part.')
            break
        if step not in ATTRIBUTES:
            raise TemplateError(
                f'"{text}": "{step}" can\'t be used. Use one of: {", ".join(sorted(ATTRIBUTES))}, parent, cf.<name>.'
            )
        if i + 1 != len(rest):
            raise TemplateError(f'"{text}": "{step}" must be the last part.')
        break
    last = rest[-1] if rest else None
    if last is None or last == 'parent':
        raise TemplateError(f'"{text}" names an object, not a value. Add .name or .slug, such as {{{text}.name}}.')
    if root == kind.own_root and rest[0] != 'cf' and rest[0] not in kind.own_attributes:
        offers = ', '.join(['cf.<name>', *sorted(kind.own_attributes)])
        raise TemplateError(f'"{text}": the {kind.label.lower()} itself offers {offers}.')
    return (root, *rest)


#: Filters a rule can apply to its whole name (the text around the number).
NAME_FILTERS = ('upper', 'lower', 'ascii', 'alnum', 'nospace', 'replace')


def parse_name_filters(text):
    """A rule's filters for the whole name, such as "ascii|nospace|lower"."""
    filters = []
    for item in (text or '').split('|'):
        if not item.strip():
            continue
        name, args = _parse_filter(item.lstrip())
        if name not in NAME_FILTERS:
            raise TemplateError(
                f'"{name}" only works on one value. For the whole name use: {", ".join(NAME_FILTERS)}.'
            )
        filters.append((name, args))
    return filters


def filter_name(text, filters):
    """
    Apply whole-name filters to rendered text, leaving the number marker and
    <missing> placeholders of Rendered.pattern alone.
    """
    if not filters or not text:
        return text
    pieces = re.split(f'({NUMBER}|<[^<>]*>)', text)
    return ''.join(
        piece if piece == NUMBER or (piece.startswith('<') and piece.endswith('>')) else apply_filters(piece, filters)
        for piece in pieces
    )


def _ascii(value):
    return unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')


def apply_filters(value, filters):
    for name, args in filters:
        if name == 'upper':
            value = value.upper()
        elif name == 'lower':
            value = value.lower()
        elif name == 'ascii':
            value = _ascii(value)
        elif name == 'alnum':
            value = ''.join(c for c in value if c.isalnum())
        elif name == 'nospace':
            value = ''.join(value.split())
        elif name == 'first':
            value = value[:args[0]]
        elif name == 'last':
            value = value[-args[0]:]
        elif name == 'default':
            value = value or args[0]
        elif name == 'before':
            value = args[0] + value if value else value
        elif name == 'after':
            value = value + args[0] if value else value
        elif name == 'replace':
            value = value.replace(args[0], args[1])
    return value


class Template:
    """A parsed template. `kind` (kinds.Kind) says where values may start."""
    def __init__(self, text, kind=DEVICE):
        self.text = text or ''
        self.parts = self._parse(self.text, kind)

    @staticmethod
    def _parse(text, kind):
        parts = []
        literal = []
        pos = 0
        numbers = 0
        for match in _TOKEN.finditer(text):
            literal.append(text[pos:match.start()])
            pos = match.end()
            token = match.group(0)
            if token == '{{':
                literal.append('{')
                continue
            if token == '}}':
                literal.append('}')
                continue
            if token in ('{', '}'):
                raise TemplateError(f'Unmatched "{token}". Write "{token}{token}" for a literal brace.')
            if literal:
                parts.append(Part('text', text=''.join(literal)))
                literal = []
            inner = match.group(1)
            if not inner.strip():
                raise TemplateError('Empty {} in the template.')
            if inner.strip() in COUNTERS:
                numbers += 1
                if numbers > 1:
                    raise TemplateError('A template can have only one counter: {n}, {a-z} or {A-Z}.')
                parts.append(Part('number', text=COUNTERS[inner.strip()]))
                continue
            path, *filters = inner.lstrip().split('|')
            parts.append(Part(
                'value', path=_parse_path(path, kind), filters=[_parse_filter(f) for f in filters],
                own_root=kind.own_root,
            ))
        literal.append(text[pos:])
        if ''.join(literal):
            parts.append(Part('text', text=''.join(literal)))
        return parts

    @property
    def has_number(self):
        return any(p.kind == 'number' for p in self.parts)

    @property
    def counter(self):
        """How the number is written: 'digits', 'lower' or 'upper' ('' without a number)."""
        return next((p.text for p in self.parts if p.kind == 'number'), '')

    @property
    def paths(self):
        return [p.path for p in self.parts if p.kind == 'value']

    def render(self, resolve):
        """
        Fill the template in. `resolve(path)` returns the value of a path
        (a string, empty when the object has none).
        """
        out = Rendered(has_number=self.has_number)
        before = True
        for part in self.parts:
            if part.kind == 'number':
                before = False
                out.pattern += NUMBER
                continue
            if part.kind == 'text':
                value = part.text
                out.pattern += value
            else:
                raw = resolve(part.path)
                raw = '' if raw is None else str(raw)
                if not raw and not part.optional:
                    out.missing.append(part.source)
                    out.pattern += f'<{part.source}>'
                value = apply_filters(raw, part.filters) if (raw or part.optional) else ''
                out.pattern += value
            if before:
                out.prefix += value
            else:
                out.suffix += value
        return out
