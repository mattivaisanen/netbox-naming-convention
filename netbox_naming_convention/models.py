"""
The plugin's records.

- NamingRule: a NetBoxModel like any NetBox object (tags, change log, custom
  fields, REST API). With netbox-change-approval installed, changes to rules
  need approval like changes to any other object.
- NamingSeries: bookkeeping, deliberately *not* a NetBoxModel: it is written
  while a device is saved, and an approval plugin must never hold that up.
  One row per series, locked while a number is taken.
"""
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from dcim.choices import DeviceStatusChoices
from netbox.models import NetBoxModel
from utilities.choices import ChoiceSet

from .numbering import MAX_DIGITS, NumberError, parse_ip_pattern, parse_skip
from .template import Template, TemplateError

__all__ = (
    'EnforcementChoices', 'NamingRule', 'NamingSeries', 'NumberScopeChoices', 'NumberSourceChoices',
    'TagMatchChoices',
)


class NumberSourceChoices(ChoiceSet):
    SEQUENCE = 'sequence'
    IP = 'ip'

    CHOICES = (
        (SEQUENCE, _('Running number'), 'blue'),
        (IP, _('From primary IP'), 'purple'),
    )


class NumberScopeChoices(ChoiceSet):
    SHARED = 'shared'
    NAME = 'name'

    CHOICES = (
        (SHARED, _('Shared: counts per text before the number'), 'blue'),
        (NAME, _('Whole name: counts per full name'), 'cyan'),
    )


class EnforcementChoices(ChoiceSet):
    OFF = 'off'
    WARN = 'warn'
    REFUSE = 'refuse'

    CHOICES = (
        (OFF, _('Off: only suggest and fill in'), 'gray'),
        (WARN, _('Warn: flag names that do not fit'), 'yellow'),
        (REFUSE, _('Refuse: new names must fit'), 'red'),
    )


class TagMatchChoices(ChoiceSet):
    ALL = 'all'
    ANY = 'any'

    CHOICES = (
        (ALL, _('All of the tags'), 'blue'),
        (ANY, _('Any of the tags'), 'cyan'),
    )


class NamingRule(NetBoxModel):
    name = models.CharField(verbose_name=_('name'), max_length=100, unique=True)
    description = models.CharField(verbose_name=_('description'), max_length=200, blank=True)
    enabled = models.BooleanField(verbose_name=_('enabled'), default=True)
    priority = models.PositiveIntegerField(
        verbose_name=_('priority'), default=100,
        help_text=_('Rules are checked from the lowest number up; the first that matches names the device.'),
    )

    # Conditions. A rule needs a role or a device type; everything else is
    # optional. Within one condition any listed value matches; all conditions
    # must match.
    roles = models.ManyToManyField(
        to='dcim.DeviceRole', related_name='+', blank=True, verbose_name=_('roles'),
        help_text=_('Child roles match too.'),
    )
    device_types = models.ManyToManyField(
        to='dcim.DeviceType', related_name='+', blank=True, verbose_name=_('device types'),
    )
    regions = models.ManyToManyField(
        to='dcim.Region', related_name='+', blank=True, verbose_name=_('regions'),
        help_text=_('Sites in child regions match too.'),
    )
    site_groups = models.ManyToManyField(
        to='dcim.SiteGroup', related_name='+', blank=True, verbose_name=_('site groups'),
    )
    sites = models.ManyToManyField(to='dcim.Site', related_name='+', blank=True, verbose_name=_('sites'))
    locations = models.ManyToManyField(
        to='dcim.Location', related_name='+', blank=True, verbose_name=_('locations'),
        help_text=_('Child locations match too.'),
    )
    tenants = models.ManyToManyField(to='tenancy.Tenant', related_name='+', blank=True, verbose_name=_('tenants'))
    platforms = models.ManyToManyField(
        to='dcim.Platform', related_name='+', blank=True, verbose_name=_('platforms'),
    )
    statuses = ArrayField(
        base_field=models.CharField(max_length=50, choices=DeviceStatusChoices),
        blank=True, default=list, verbose_name=_('statuses'),
    )
    match_tags = models.ManyToManyField(
        to='extras.Tag', related_name='+', blank=True, verbose_name=_('device tags'),
        help_text=_('Tags the device must have (for example "ot").'),
    )
    tag_match = models.CharField(
        verbose_name=_('tag match'), max_length=10, choices=TagMatchChoices, default=TagMatchChoices.ALL,
    )
    constraint = models.JSONField(
        verbose_name=_('advanced condition'), blank=True, null=True,
        help_text=_(
            'Optional. A filter in the format of NetBox permission constraints, for example '
            '{"serial__startswith": "FOC"}, or a list of such filters (any may match).'
        ),
    )

    # The name.
    template = models.CharField(
        verbose_name=_('template'), max_length=200,
        help_text=_(
            'Literal text, {n} for the number and values such as {site.name|first:2|upper} or '
            '{rack.name|before:_|optional}. See the documentation for all values and filters.'
        ),
    )
    number_source = models.CharField(
        verbose_name=_('number source'), max_length=10, choices=NumberSourceChoices,
        default=NumberSourceChoices.SEQUENCE,
    )
    ip_pattern = models.CharField(
        verbose_name=_('IP pattern'), max_length=200, blank=True,
        help_text=_(
            'Only for "From primary IP": a mask such as *.*.*.N (the octet marked N is the number) or a '
            'regular expression with one group.'
        ),
    )
    number_digits = models.PositiveSmallIntegerField(
        verbose_name=_('digits'), default=3, validators=[MinValueValidator(1), MaxValueValidator(MAX_DIGITS)],
        help_text=_('Numbers are padded with zeros to this many digits (3: 001).'),
    )
    number_first = models.PositiveIntegerField(verbose_name=_('first number'), default=1)
    number_last = models.PositiveIntegerField(
        verbose_name=_('last number'), blank=True, null=True,
        help_text=_('Leave empty for the largest number the digits allow (999 for 3 digits).'),
    )
    skip_numbers = models.CharField(
        verbose_name=_('numbers never handed out'), max_length=200, blank=True,
        help_text=_('Numbers and ranges, for example "0, 100-199".'),
    )
    fill_gaps = models.BooleanField(
        verbose_name=_('fill gaps'), default=False,
        help_text=_(
            'Hand out the lowest free number, including those of deleted devices. Off: always one more '
            'than the highest number ever handed out.'
        ),
    )
    number_scope = models.CharField(
        verbose_name=_('number scope'), max_length=10, choices=NumberScopeChoices,
        default=NumberScopeChoices.SHARED,
    )
    enforcement = models.CharField(
        verbose_name=_('enforcement'), max_length=10, choices=EnforcementChoices,
        default=EnforcementChoices.WARN,
    )
    comments = models.TextField(verbose_name=_('comments'), blank=True)

    class Meta:
        ordering = ('priority', 'name')
        verbose_name = _('naming rule')
        verbose_name_plural = _('naming rules')

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('plugins:netbox_naming_convention:namingrule', args=[self.pk])

    def get_number_source_color(self):
        return NumberSourceChoices.colors.get(self.number_source)

    def get_enforcement_color(self):
        return EnforcementChoices.colors.get(self.enforcement)

    @property
    def last_number(self):
        return self.number_last if self.number_last is not None else 10 ** self.number_digits - 1

    @property
    def parsed_template(self):
        return Template(self.template)

    @property
    def skip_ranges(self):
        try:
            return parse_skip(self.skip_numbers)
        except NumberError:
            return []

    def format_number(self, number):
        return str(number).zfill(self.number_digits)

    def clean(self):
        super().clean()
        errors = {}
        try:
            template = Template(self.template)
        except TemplateError as e:
            errors['template'] = str(e)
        else:
            if self.number_source == NumberSourceChoices.IP and not template.has_number:
                errors['template'] = _('A rule that reads its number from the IP needs {n} in the template.')
        if self.number_source == NumberSourceChoices.IP:
            try:
                parse_ip_pattern(self.ip_pattern)
            except NumberError as e:
                errors['ip_pattern'] = str(e)
        try:
            parse_skip(self.skip_numbers)
        except NumberError as e:
            errors['skip_numbers'] = str(e)
        if self.number_last is not None and self.number_last < self.number_first:
            errors['number_last'] = _('The last number must not be lower than the first.')
        if self.constraint is not None and not isinstance(self.constraint, (dict, list)):
            errors['constraint'] = _('Use a JSON object or a list of objects.')
        if errors:
            raise ValidationError(errors)


class NamingSeries(models.Model):
    """
    One series (see numbering.py): the highest number ever handed out, so a
    deleted device's number does not come back when gap filling is off. The
    row is locked (`select_for_update()`) while a device takes a number, so
    two devices saved at the same time never get the same one.
    """
    key = models.CharField(verbose_name=_('series'), max_length=255, unique=True)
    high_water = models.PositiveIntegerField(verbose_name=_('highest number handed out'), default=0)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('key',)
        verbose_name = _('naming series')
        verbose_name_plural = _('naming series')

    def __str__(self):
        return self.key
