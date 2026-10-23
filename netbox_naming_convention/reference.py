"""
What templates can use, for the "Template reference" page (linked from the
rule form). Kept next to the code it describes: tests check that every root
and filter in template.py is listed here.
"""
from django.utils.translation import gettext_lazy as _

#: (example, what it gives) for each place a value can come from.
VALUES = (
    ('{site.name}', _('the site: name, slug, facility, cf.<name>')),
    ('{location.name}', _('the location: name, slug, parent, cf.<name>')),
    ('{rack.name}', _('the rack: name, facility, serial, asset_tag, cf.<name>')),
    ('{role.name}', _('the device role: name, slug, parent (role.parent.name for the parent role)')),
    ('{device_type.model}', _('the device type: model, slug, part_number')),
    ('{manufacturer.name}', _('the manufacturer of the device type: name, slug')),
    ('{tenant.slug}', _('the tenant: name, slug')),
    ('{platform.name}', _('the platform: name, slug')),
    ('{region.name}', _('the region of the site: name, slug, parent')),
    ('{site_group.slug}', _('the site group of the site: name, slug, parent')),
    ('{device.serial}', _('the device itself: serial, asset_tag, label')),
    ('{cf.code}', _('a custom field of the device (site.cf.code for one of the site, and so on)')),
)

#: The roots VALUES covers (checked by the tests).
ROOTS_COVERED = (
    'site', 'location', 'rack', 'role', 'device_type', 'manufacturer', 'tenant', 'platform', 'region',
    'site_group', 'device',
)

#: (filter, what it does, example).
FILTERS = (
    ('upper', _('upper case'), '{site.slug|upper}: ams1 → AMS1'),
    ('lower', _('lower case'), '{role.name|lower}: Switch → switch'),
    ('first:N', _('the first N characters'), '{site.name|first:3}: Amsterdam → Ams'),
    ('last:N', _('the last N characters'), '{rack.name|last:2}: R012 → 12'),
    ('ascii', _('removes accents'), '{site.name|ascii}: Zürich → Zurich'),
    ('alnum', _('keeps only letters and digits'), '{rack.name|alnum}: R-01 → R01'),
    ('nospace', _('removes spaces'), '{location.name|nospace}: Floor 2 → Floor2'),
    ('replace:old:new', _('replaces text; leave new out to remove it'), '{rack.name|replace:-:_}: R-01 → R_01'),
    ('default:X', _('X when the value is empty'), '{tenant.slug|default:shared}'),
    ('before:X', _('adds X before the value, only when there is one'), '{rack.name|before:-}: R01 → -R01'),
    ('after:X', _('adds X after the value, only when there is one'), '{location.slug|after:-}'),
    ('optional', _('leaves the part out when the value is empty, instead of waiting for it'),
     '{rack.name|before:-|optional}'),
)

#: Other syntax.
OTHER = (
    ('{n}', _('the number, padded with zeros to the rule\'s digits. At most one per template.')),
    ('{{ }}', _('literal braces')),
    (_('anything else'), _('literal text, as written')),
)
