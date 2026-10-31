"""
The plugin's records.

- NamingRule: a NetBoxModel like any NetBox object (tags, change log, custom
  fields, REST API). With netbox-change-approval installed, changes to rules
  need approval like changes to any other object.
- NamingSeries: bookkeeping, deliberately *not* a NetBoxModel: it is written
  while an object is saved, and an approval plugin must never hold that up.
  One row per series, locked while a number is taken.
- AssignedName: bookkeeping too. Which names a rule gave (filled in when the
  object was added, or suggested and accepted on edit), for the object's
  page and change requests.

A rule names one kind of object (`object_type`: devices, virtual machines
or racks, see kinds.py); which of its conditions apply depends on that.
"""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from netbox.models import NetBoxModel
from utilities.choices import ChoiceSet

from .kinds import DEVICE, KINDS, ObjectTypeChoices
from .numbering import LETTERS, MAX_DIGITS, NumberError, letter, parse_ip_pattern, parse_skip
from .template import Template, TemplateError, parse_name_filters

__all__ = (
    'AssignedName', 'AssignedHowChoices', 'EnforcementChoices', 'NamingRule', 'RequiredValueChoices', 'NamingSeries',
    'NumberScopeChoices', 'NumberSourceChoices', 'ObjectTypeChoices',
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


class RequiredValueChoices(ChoiceSet):
    """
    Fields a rule can wait for before it names an object. Which of them a
    rule offers depends on its kind (`Kind.wait_for`).
    """
    SITE = 'site'
    LOCATION = 'location'
    RACK = 'rack'
    CLUSTER = 'cluster'
    ROLE = 'role'
    DEVICE_TYPE = 'device_type'
    VM_TYPE = 'virtual_machine_type'
    RACK_TYPE = 'rack_type'
    TENANT = 'tenant'
    PLATFORM = 'platform'
    FACILITY_ID = 'facility_id'
    SERIAL = 'serial'
    ASSET_TAG = 'asset_tag'

    CHOICES = (
        (SITE, _('Site')),
        (LOCATION, _('Location')),
        (RACK, _('Rack')),
        (CLUSTER, _('Cluster')),
        (ROLE, _('Role')),
        (DEVICE_TYPE, _('Device type')),
        (VM_TYPE, _('Virtual machine type')),
        (RACK_TYPE, _('Rack type')),
        (TENANT, _('Tenant')),
        (PLATFORM, _('Platform')),
        (FACILITY_ID, _('Facility ID')),
        (SERIAL, _('Serial number')),
        (ASSET_TAG, _('Asset tag')),
    )


def default_required_values():
    """The fields NetBox's device form requires (status always has a value); see Kind.default_wait_for."""
    return list(DEVICE.default_wait_for)


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
        help_text=_(
            'Rules are checked from the lowest number up; the first that matches names the device. On the '
            'same priority, the rule with more kinds of conditions wins.'
        ),
    )

    object_type = models.CharField(
        verbose_name=_('names'), max_length=30, choices=ObjectTypeChoices, default=ObjectTypeChoices.DEVICE,
        help_text=_('The kind of object the rule names.'),
    )

    # Conditions. Which apply depends on the object type (kinds.py); a device
    # rule needs a role or a device type. Within one condition any listed
    # value matches; all conditions must match.
    roles = models.ManyToManyField(
        to='dcim.DeviceRole', related_name='+', blank=True, verbose_name=_('roles'),
        help_text=_('Child roles match too.'),
    )
    device_types = models.ManyToManyField(
        to='dcim.DeviceType', related_name='+', blank=True, verbose_name=_('device types'),
    )
    vm_types = models.ManyToManyField(
        to='virtualization.VirtualMachineType', related_name='+', blank=True,
        verbose_name=_('virtual machine types'),
    )
    clusters = models.ManyToManyField(
        to='virtualization.Cluster', related_name='+', blank=True, verbose_name=_('clusters'),
    )
    rack_roles = models.ManyToManyField(
        to='dcim.RackRole', related_name='+', blank=True, verbose_name=_('rack roles'),
    )
    rack_types = models.ManyToManyField(
        to='dcim.RackType', related_name='+', blank=True, verbose_name=_('rack types'),
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
    # The choices depend on the object type; clean() checks them.
    statuses = ArrayField(
        base_field=models.CharField(max_length=50), blank=True, default=list, verbose_name=_('statuses'),
    )
    match_tags = models.ManyToManyField(
        to='extras.Tag', related_name='+', blank=True, verbose_name=_('tags'),
        help_text=_('Tags the object must have.'),
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
            'Literal text, {n} for the number ({a-z} or {A-Z} to count in letters) and values of the object '
            'such as {site.slug|upper} or {rack.name|before:-|optional}.'
        ),
    )
    required_values = ArrayField(
        base_field=models.CharField(max_length=20, choices=RequiredValueChoices),
        blank=True, default=default_required_values, verbose_name=_('wait for'),
        help_text=_(
            'The name is filled in only once these are set, besides the values the template uses. New device '
            'rules wait for the fields the device form requires.'
        ),
    )
    name_filters = models.CharField(
        verbose_name=_('filters for the whole name'), max_length=200, blank=True,
        help_text=_(
            'Applied to the whole name after the template, for example ascii|nospace|lower. The number is '
            'not changed. Filters: upper, lower, ascii, alnum, nospace, replace:old:new.'
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
        help_text=_(
            'Numbers are padded with zeros to this many digits (3 gives 007). Also for numbers from the IP; '
            '1 leaves them as they are.'
        ),
    )
    number_first = models.PositiveIntegerField(verbose_name=_('first number'), default=1)
    number_last = models.PositiveIntegerField(
        verbose_name=_('last number'), blank=True, null=True,
        help_text=_(
            'Leave empty for the largest number the digits allow (999 for 3 digits). Letters count a=1 to z=26.'
        ),
    )
    skip_numbers = models.CharField(
        verbose_name=_('numbers never handed out'), max_length=200, blank=True,
        help_text=_('Numbers and ranges, for example "0, 100-199". Letters for a letter counter: "i, o".'),
    )
    fill_gaps = models.BooleanField(
        verbose_name=_('fill gaps'), default=False,
        help_text=_(
            'Hand out the lowest free number, including those of deleted objects. Off: always one more '
            'than the highest number ever handed out.'
        ),
    )
    number_scope = models.CharField(
        verbose_name=_('number scope'), max_length=10, choices=NumberScopeChoices,
        default=NumberScopeChoices.SHARED,
    )
    member_suffix = models.CharField(
        verbose_name=_('member suffix'), max_length=20, blank=True,
        help_text=_(
            'Optional. An ending a name may have after the number, for stack or cluster members. '
            '# is one or more digits: -# lets SW005-1 and SW005-2 follow the rule, both as number 5.'
        ),
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
    def kind(self):
        """The kinds.Kind this rule names (devices for an unknown object type)."""
        return KINDS.get(self.object_type, DEVICE)

    def get_object_type_color(self):
        return ObjectTypeChoices.colors.get(self.object_type)

    @property
    def letters(self):
        """Whether the template counts in letters ({a-z} or {A-Z}) instead of digits."""
        return self.counter in ('lower', 'upper')

    @property
    def counter(self):
        """The template's counter (template.COUNTERS), '' without one or with a broken template."""
        try:
            return self.parsed_template.counter
        except TemplateError:
            return ''

    @property
    def last_number(self):
        if self.number_last is not None:
            return self.number_last
        return len(LETTERS) if self.letters else 10 ** self.number_digits - 1

    @property
    def first_text(self):
        """The range's ends for the rule page: 1 and 999, or a and z."""
        return self.format_number(self.number_first) if self.letters else str(self.number_first)

    @property
    def last_text(self):
        return self.format_number(self.last_number) if self.letters else str(self.last_number)

    @property
    def parsed_template(self):
        return Template(self.template, self.kind)

    #: Every condition field of any kind (each kind uses some, see kinds.py).
    CONDITION_FIELDS = (
        'roles', 'device_types', 'vm_types', 'clusters', 'rack_roles', 'rack_types', 'regions', 'site_groups',
        'sites', 'locations', 'tenants', 'platforms', 'match_tags',
    )

    @property
    def specificity(self):
        """How many kinds of conditions the rule has; breaks ties between equal priorities."""
        count = sum(1 for name in self.kind.condition_fields if getattr(self, name).all())
        return count + bool(self.statuses) + bool(self.constraint)

    @property
    def parsed_name_filters(self):
        try:
            return parse_name_filters(self.name_filters)
        except TemplateError:
            return []

    @property
    def skip_ranges(self):
        try:
            return parse_skip(self.skip_numbers, self.letters)
        except NumberError:
            return []

    def format_number(self, number):
        """The number as the name writes it: 007, or c / C for a letter counter."""
        counter = self.counter
        if counter in ('lower', 'upper') and 1 <= number <= len(LETTERS):
            text = letter(number)
            return text.upper() if counter == 'upper' else text
        return str(number).zfill(self.number_digits)

    def _default_wait_for(self):
        """A new rule of another kind left at the device default (the API, scripts) waits for its own defaults."""
        if self.pk is None and self.kind is not DEVICE and self.required_values == default_required_values():
            self.required_values = list(self.kind.default_wait_for)

    def save(self, *args, **kwargs):
        self._default_wait_for()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        kind = self.kind
        if self.object_type not in KINDS:
            errors['object_type'] = _('Unknown object type.')
        try:
            template = Template(self.template, kind)
        except TemplateError as e:
            errors['template'] = str(e)
        else:
            letters = template.counter in ('lower', 'upper')
            if self.number_source == NumberSourceChoices.IP and not template.has_number:
                errors['template'] = _('A rule that reads its number from the IP needs {n} in the template.')
            elif self.number_source == NumberSourceChoices.IP and letters:
                errors['template'] = _('A number from the IP is written in digits: use {n}, not letters.')
            elif letters and not 1 <= self.number_first <= len(LETTERS):
                errors['number_first'] = _('Letters count from 1 (a) to 26 (z).')
            elif letters and self.number_last is not None and self.number_last > len(LETTERS):
                errors['number_last'] = _('Letters count from 1 (a) to 26 (z).')
        if self.number_source == NumberSourceChoices.IP and not kind.has_primary_ip:
            errors['number_source'] = _('{kinds} have no primary IP to read a number from.').format(
                kinds=kind.label_plural.capitalize(),
            )
        statuses = dict(kind.statuses.CHOICES)
        if unknown := [status for status in self.statuses or [] if status not in statuses]:
            errors['statuses'] = _('Not a status of {kinds}: {statuses}.').format(
                kinds=kind.label_plural, statuses=', '.join(unknown),
            )
        self._default_wait_for()
        if unknown := [value for value in self.required_values or [] if value not in kind.wait_for]:
            errors['required_values'] = _('{kinds} have no {values}.').format(
                kinds=kind.label_plural.capitalize(), values=', '.join(unknown),
            )
        try:
            parse_name_filters(self.name_filters)
        except TemplateError as e:
            errors['name_filters'] = str(e)
        if self.number_source == NumberSourceChoices.IP:
            try:
                parse_ip_pattern(self.ip_pattern)
            except NumberError as e:
                errors['ip_pattern'] = str(e)
        try:
            parse_skip(self.skip_numbers, self.letters)
        except NumberError as e:
            errors['skip_numbers'] = str(e)
        if self.member_suffix and (self.member_suffix[0] == '#' or self.member_suffix[0].isdigit()):
            # SW005 + "#" would be SW0051: the number and the ending must be told apart.
            errors['member_suffix'] = _('The member suffix must start with something other than a digit, such as -#.')
        if self.number_last is not None and self.number_last < self.number_first:
            errors['number_last'] = _('The last number must not be lower than the first.')
        if self.constraint is not None:
            if isinstance(self.constraint, (dict, list)):
                from .matching import constraint_errors

                if problems := constraint_errors(self.constraint, kind):
                    errors['constraint'] = problems
            else:
                errors['constraint'] = _('Use a JSON object or a list of objects.')
        if errors:
            raise ValidationError(errors)


class NamingSeries(models.Model):
    """
    One series (see numbering.py): the highest number ever handed out, so a
    deleted device's number does not come back when gap filling is off. The
    row is locked (`select_for_update()`) while a device takes a number, so
    two devices saved at the same time never get the same one.

    `released` holds numbers of devices that were never approved (their
    create request was rejected, withdrawn or expired in
    netbox-change-approval). They are handed out again first, even with gap
    filling off.
    """
    key = models.CharField(verbose_name=_('series'), max_length=255, unique=True)
    high_water = models.PositiveIntegerField(verbose_name=_('highest number handed out'), default=0)
    released = ArrayField(
        base_field=models.PositiveIntegerField(), verbose_name=_('numbers given back'), blank=True, default=list,
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('key',)
        verbose_name = _('naming series')
        verbose_name_plural = _('naming series')

    def __str__(self):
        return self.key


class AssignedHowChoices(ChoiceSet):
    AUTO = 'auto'
    SUGGESTED = 'suggested'

    CHOICES = (
        (AUTO, _('Filled in by the rule'), 'green'),
        (SUGGESTED, _('Suggested by the rule and accepted'), 'cyan'),
    )


class AssignedName(models.Model):
    """
    A name a rule gave an object (device, virtual machine, rack). Kept per
    object and name; removed with the object (signals.py).
    """
    object_type = models.ForeignKey(to=ContentType, on_delete=models.CASCADE, related_name='+')
    object_id = models.PositiveBigIntegerField()
    object = GenericForeignKey('object_type', 'object_id')
    name = models.CharField(verbose_name=_('name'), max_length=100)
    rule = models.ForeignKey(to=NamingRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    #: The rule's name at the time, kept when the rule is deleted.
    rule_name = models.CharField(verbose_name=_('rule'), max_length=100)
    how = models.CharField(verbose_name=_('how'), max_length=10, choices=AssignedHowChoices)
    created = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created',)
        verbose_name = _('assigned name')
        verbose_name_plural = _('assigned names')
        constraints = [
            models.UniqueConstraint(
                fields=('object_type', 'object_id', 'name'), name='netbox_naming_convention_assigned_name',
            ),
        ]

    def __str__(self):
        return self.name

    def get_how_color(self):
        return AssignedHowChoices.colors.get(self.how)

    @classmethod
    def of(cls, obj):
        """The names given to `obj` (any model instance)."""
        if not obj.pk:
            return cls.objects.none()
        return cls.objects.filter(object_type=ContentType.objects.get_for_model(obj), object_id=obj.pk)

    @classmethod
    def record(cls, obj, name, rule, how):
        cls.objects.update_or_create(
            object_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, name=name,
            defaults={'rule': rule, 'rule_name': rule.name[:100], 'how': how},
        )

    @classmethod
    def lookup(cls, obj, name):
        if not obj.pk or not name:
            return None
        return cls.of(obj).filter(name=name).select_related('rule').first()
