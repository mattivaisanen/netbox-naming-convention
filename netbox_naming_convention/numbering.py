"""
Numbers of a series.

A series is the text a number counts in: the prefix before the number
("shared" scope: AMS1-SW014-R01 and AMS1-SW015-R02 share AMS1-SW), or the
prefix and suffix together ("whole name" scope: AMS1-SW001-R01 and
AMS1-SW001-R02 are both number 1, of AMS1-SW#-R01 and AMS1-SW#-R02).

Used numbers come from the names devices have in NetBox, compared without
case, so names given before the rule existed count. With gap filling off,
the series also remembers the highest number it ever handed out
(NamingSeries.high_water), so the number of a deleted device never comes
back.
"""
import ipaddress
import re

__all__ = (
    'NumberError', 'parse_skip', 'series_key', 'name_regex', 'used_numbers', 'next_number',
    'number_from_ip', 'parse_ip_pattern',
)

#: Longest a number may be, in digits.
MAX_DIGITS = 9


class NumberError(ValueError):
    pass


def parse_skip(text):
    """
    "0, 100-199, 666" -> a list of (low, high) ranges. Raises NumberError on
    anything else.
    """
    ranges = []
    for item in (text or '').replace(';', ',').split(','):
        item = item.strip()
        if not item:
            continue
        low, sep, high = item.partition('-')
        try:
            low = int(low)
            high = int(high) if sep else low
        except ValueError:
            raise NumberError(f'"{item}" is not a number or a range such as 100-199.') from None
        if low < 0 or high < low:
            raise NumberError(f'"{item}" is not a valid range.')
        ranges.append((low, high))
    return ranges


def is_skipped(number, ranges):
    return any(low <= number <= high for low, high in ranges)


def _past_skipped(number, ranges):
    """`number`, or the first number after the skipped ranges it falls in."""
    moved = True
    while moved:
        moved = False
        for low, high in ranges:
            if low <= number <= high:
                number, moved = high + 1, True
    return number


def series_key(prefix, suffix, scope):
    """The key a series is stored under: case does not matter."""
    if scope == 'name':
        return f'{prefix}#{suffix}'.lower()
    return prefix.lower()


def name_regex(prefix, suffix, scope):
    """
    A regular expression that matches the names of a series and captures
    their number. For PostgreSQL (`name__iregex`) and Python alike.
    """
    if scope == 'name':
        return '^' + re.escape(prefix) + r'([0-9]+)' + re.escape(suffix) + '$'
    # Shared scope: whatever follows the number is decoration, but it must not
    # be another digit (AMS1-SW1540 is number 1540, not 154).
    return '^' + re.escape(prefix) + r'([0-9]+)([^0-9]|$)'


def used_numbers(prefix, suffix, scope, exclude_pk=None):
    """Numbers devices in NetBox already have in this series."""
    from dcim.models import Device

    pattern = name_regex(prefix, suffix, scope)
    names = Device.objects.filter(name__iregex=pattern)
    if exclude_pk:
        names = names.exclude(pk=exclude_pk)
    compiled = re.compile(pattern, re.IGNORECASE)
    used = set()
    for name in names.values_list('name', flat=True):
        match = compiled.match(name)
        if match:
            used.add(int(match.group(1)))
    return used


def next_number(used, *, first, last, skip=(), fill_gaps=False, high_water=0):
    """
    The number to hand out next, or NumberError when the series is full.

    - Gap filling on: the lowest free number from `first` on.
    - Gap filling off: one more than the highest number in use or ever handed
      out (`high_water`), and at least `first`.

    Numbers above `last` (a name typed by hand, such as SW5000 in a 3-digit
    series) are outside the range and don't count. Skipped ranges are jumped
    over, not walked through, so "1-999999" costs nothing.
    """
    used = {number for number in used if number <= last}
    if fill_gaps:
        number = _past_skipped(first, skip)
        while number <= last:
            if number not in used:
                return number
            number = _past_skipped(number + 1, skip)
    else:
        number = _past_skipped(max([first - 1, high_water, *used]) + 1, skip)
        if number <= last:
            return number
    raise NumberError(f'No free numbers left ({first} to {last}).')


#: A mask such as *.*.*.N or 10.*.N.*: one N, the other octets * or a number.
_MASK = re.compile(r'^(\*|N|[0-9]{1,3})(\.(\*|N|[0-9]{1,3})){3}$', re.IGNORECASE)


def parse_ip_pattern(pattern):
    """
    A mask (`*.*.*.N`: the number is the octet marked N) or a regular
    expression with one group (or a group named `n`), matched against the
    address without its prefix length. Returns a compiled regex.
    """
    pattern = (pattern or '').strip()
    if not pattern:
        raise NumberError('The rule reads its number from the IP but has no IP pattern.')
    if _MASK.match(pattern):
        octets = pattern.split('.')
        if sum(1 for o in octets if o.upper() == 'N') != 1:
            raise NumberError('An IP mask needs exactly one N, such as *.*.*.N.')
        parts = []
        for octet in octets:
            if octet == '*':
                parts.append(r'[0-9]{1,3}')
            elif octet.upper() == 'N':
                parts.append(r'(?P<n>[0-9]{1,3})')
            else:
                parts.append(re.escape(octet))
        return re.compile('^' + r'\.'.join(parts) + '$')
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        raise NumberError(f'The IP pattern is not a valid mask or regular expression: {e}.') from None
    if compiled.groups < 1:
        raise NumberError('The IP pattern needs a group that captures the number, such as \\.([0-9]+)$.')
    return compiled


def number_from_ip(pattern, address):
    """
    The number in `address` (an IP with or without prefix length), or None
    when the address doesn't match.
    """
    if not address:
        return None
    text = str(address).split('/')[0]
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return None
    match = parse_ip_pattern(pattern).search(text)
    if not match:
        return None
    value = match.groupdict().get('n') or match.group(1)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
