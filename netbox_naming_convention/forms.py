from django import forms
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from dcim.models import DeviceRole, DeviceType, Location, Platform, RackRole, RackType, Region, Site, SiteGroup
from extras.models import Tag
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from tenancy.models import Tenant
from utilities.forms.fields import (
    CommentField, DynamicModelChoiceField, DynamicModelMultipleChoiceField, JSONField, TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.utils import get_field_value
from utilities.forms.widgets import APISelect, DatePicker, HTMXSelect
from virtualization.models import Cluster, VirtualMachineType

from .kinds import DEVICE, KINDS
from .models import EnforcementChoices, NamingRule, NumberSourceChoices, ObjectTypeChoices, RequiredValueChoices
from .naming import RESERVE_LIMIT


class PreviewObjectSelect(APISelect):
    """
    The object picker of the rule form's preview, with the preview below it:
    the template posts the whole form to the preview view whenever it
    changes (see preview.py).
    """
    template_name = 'netbox_naming_convention/inc/preview_object.html'
    preview_url = ''

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['preview_url'] = self.preview_url
        return context


def _many(label, model):
    return DynamicModelMultipleChoiceField(label=label, queryset=model.objects.all(), required=False)


class NamingRuleForm(NetBoxModelForm):
    """
    The rule form. The object type and the number source are HTMXSelects:
    changing them draws the form again with only the fields that apply
    (like NetBox's rack form does for rack types).
    """
    roles = _many(_('Roles'), DeviceRole)
    device_types = _many(_('Device types'), DeviceType)
    vm_types = _many(_('Virtual machine types'), VirtualMachineType)
    clusters = _many(_('Clusters'), Cluster)
    rack_roles = _many(_('Rack roles'), RackRole)
    rack_types = _many(_('Rack types'), RackType)
    regions = _many(_('Regions'), Region)
    site_groups = _many(_('Site groups'), SiteGroup)
    sites = _many(_('Sites'), Site)
    locations = _many(_('Locations'), Location)
    tenants = _many(_('Tenants'), Tenant)
    platforms = _many(_('Platforms'), Platform)
    statuses = forms.MultipleChoiceField(label=_('Statuses'), required=False)
    required_values = forms.MultipleChoiceField(
        label=_('Wait for'), required=False, help_text=NamingRule._meta.get_field('required_values').help_text,
    )
    match_tags = DynamicModelMultipleChoiceField(
        label=_('Tags'), queryset=Tag.objects.all(), required=False, help_text=_('Tags the object must have.'),
    )
    constraint = JSONField(label=_('Advanced condition'), required=False)
    comments = CommentField()
    # Not saved: only for the preview. Its queryset follows the object type.
    preview_object = DynamicModelChoiceField(
        label=_('Try on'), queryset=DEVICE.model.objects.all(), required=False, widget=PreviewObjectSelect,
    )

    class Meta:
        model = NamingRule
        fields = (
            'name', 'description', 'enabled', 'priority', 'object_type', *NamingRule.CONDITION_FIELDS, 'statuses',
            'tag_match', 'constraint', 'template', 'name_filters', 'name_match', 'required_values', 'number_source',
            'ip_pattern', 'number_digits', 'number_first', 'number_last', 'skip_numbers', 'fill_gaps', 'number_scope',
            'member_suffix', 'enforcement', 'comments', 'tags',
        )
        widgets = {
            'template': forms.TextInput(attrs={'class': 'font-monospace'}),
            'name_filters': forms.TextInput(attrs={'class': 'font-monospace'}),
            'member_suffix': forms.TextInput(attrs={'class': 'font-monospace'}),
            'object_type': HTMXSelect(),
            'number_source': HTMXSelect(),
        }

    #: Fields that mean nothing for the other number source.
    SEQUENCE_ONLY = ('number_first', 'number_last', 'skip_numbers', 'fill_gaps')
    IP_ONLY = ('ip_pattern',)
    #: Conditions every kind has besides its own (Kind.conditions).
    SHARED_CONDITIONS = ('statuses', 'match_tags', 'tag_match', 'constraint')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kind = KINDS.get(get_field_value(self, 'object_type')) or DEVICE
        self.kind = kind
        # Left out (older scripts, the API's forms): a device rule.
        self.fields['object_type'].required = False
        # Left out (forms from before name matching): the whole name.
        self.fields['name_match'].required = False
        self._fit_conditions(kind)
        self._fit_number(kind)
        self.fields['template'].help_text = format_html(
            '{} <a href="{}" target="_blank">{}</a>',
            self.fields['template'].help_text,
            reverse('plugins:netbox_naming_convention:reference') + f'?object_type={kind.key}',
            _('All values and filters'),
        )
        preview = self.fields['preview_object']
        preview.queryset = kind.model.objects.all()
        preview.label = _('Try on {kind}').format(kind=kind.label.lower())
        url = reverse('plugins:netbox_naming_convention:namingrule_preview')
        preview.widget.preview_url = f'{url}?rule={self.instance.pk}' if self.instance.pk else url

        own = [c.field for c in kind.conditions]
        required = [name for name in own if name in kind.required_conditions]
        if required:
            kind_fieldset = FieldSet(*required, name=_('Kind of device (one of these is required)'))
        else:
            kind_fieldset = None
        number = [name for name in (
            'number_source', 'number_digits', 'number_first', 'number_last', 'skip_numbers', 'fill_gaps',
            'number_scope', 'member_suffix', 'ip_pattern',
        ) if name in self.fields]
        self.fieldsets = tuple(fieldset for fieldset in (
            FieldSet('name', 'description', 'enabled', 'priority', 'object_type', 'tags', name=_('Rule')),
            kind_fieldset,
            FieldSet(
                *[name for name in own if name not in required], *self.SHARED_CONDITIONS,
                name=_('Other conditions (optional)') if required else _('Conditions (optional)'),
            ),
            FieldSet('template', 'name_filters', 'name_match', 'required_values', name=_('Name')),
            FieldSet('preview_object', name=_('Preview')),
            FieldSet(*number, name=_('Number')),
            FieldSet('enforcement', name=_('Enforcement')),
        ) if fieldset is not None)

    def _fit_conditions(self, kind):
        """Only the conditions, statuses and waits the object type has."""
        for name in NamingRule.CONDITION_FIELDS:
            if name not in kind.condition_fields:
                del self.fields[name]
        self.fields['statuses'].choices = kind.statuses.CHOICES
        waits = dict(RequiredValueChoices.CHOICES)
        self.fields['required_values'].choices = [(key, waits[key]) for key in kind.wait_for]
        if not self.is_bound:
            current = self.initial.get('required_values', self.instance.required_values) or []
            if isinstance(current, str):
                current = [current]
            if self.instance.pk is None and list(current) == list(DEVICE.default_wait_for):
                # A new rule starts with its own kind's defaults.
                current = kind.default_wait_for
            self.initial['required_values'] = [key for key in current if key in kind.wait_for]

    def _fit_number(self, kind):
        """Only the number fields of the chosen source; no IP source for objects without a primary IP."""
        if not kind.has_primary_ip:
            self.fields['number_source'].choices = [
                choice for choice in self.fields['number_source'].choices if choice[0] != NumberSourceChoices.IP
            ]
        source = get_field_value(self, 'number_source') or NumberSourceChoices.SEQUENCE
        if not kind.has_primary_ip:
            source = NumberSourceChoices.SEQUENCE
        for name in self.IP_ONLY if source == NumberSourceChoices.SEQUENCE else self.SEQUENCE_ONLY:
            del self.fields[name]

    def _save_m2m(self):
        super()._save_m2m()
        # Conditions of another object type are not on the form, so Django
        # leaves them alone. Clear them, or a rule changed from devices to
        # racks keeps its device roles (and the API refuses to edit it).
        for name in NamingRule.CONDITION_FIELDS:
            if name not in self.kind.condition_fields:
                getattr(self.instance, name).clear()

    def clean_object_type(self):
        return self.cleaned_data.get('object_type') or DEVICE.key

    def clean_name_match(self):
        return self.cleaned_data.get('name_match') or NamingRule._meta.get_field('name_match').default

    def clean(self):
        super().clean()
        data = self.cleaned_data
        values = {name: data.get(name) for name in NamingRule.CONDITION_FIELDS if name in self.fields}
        for name, error in self.kind.condition_errors(values).items():
            self.add_error(name, error)
        return data


class NamingRuleFilterForm(NetBoxModelFilterSetForm):
    model = NamingRule
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('enabled', 'object_type', 'role_id', 'device_type_id', 'site_id', 'number_source', 'enforcement',
                 name=_('Rule')),
    )
    enabled = forms.NullBooleanField(
        required=False, label=_('Enabled'),
        widget=forms.Select(choices=((None, '---------'), (True, _('Yes')), (False, _('No')))),
    )
    object_type = forms.MultipleChoiceField(choices=ObjectTypeChoices, required=False, label=_('Names'))
    role_id = DynamicModelMultipleChoiceField(queryset=DeviceRole.objects.all(), required=False, label=_('Role'))
    device_type_id = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(), required=False, label=_('Device type'),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    number_source = forms.MultipleChoiceField(choices=NumberSourceChoices, required=False, label=_('Number source'))
    enforcement = forms.MultipleChoiceField(choices=EnforcementChoices, required=False, label=_('Enforcement'))
    tag = TagFilterField(model)


class ReserveForm(forms.Form):
    """
    Reserve names of a rule: how many, until when, and the values the names
    are built from (the site, rack and so on of the objects to come). A value
    the rule's conditions name only one of starts filled in.
    """
    count = forms.IntegerField(label=_('How many'), min_value=1, max_value=RESERVE_LIMIT, initial=1)
    expires = forms.DateField(
        label=_('Expires'), required=False, widget=DatePicker(),
        help_text=_('After this day the numbers are free again. Empty: kept until used or removed.'),
    )
    description = forms.CharField(label=_('Description'), max_length=200, required=False)

    def __init__(self, rule, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rule = rule
        kind = rule.kind
        model = kind.model
        only = {}
        for condition in kind.conditions:
            values = list(getattr(rule, condition.field).all())
            if len(condition.path) == 1 and len(values) == 1:
                only[condition.path[0]] = values[0].pk
        #: The form's fields the names are built from.
        self.value_fields = []
        for key in kind.form_fields:
            field = model._meta.get_field(key)
            if not field.is_relation or key.startswith('primary_ip'):
                continue
            self.fields[key] = DynamicModelChoiceField(
                label=field.verbose_name.capitalize(), queryset=field.related_model.objects.all(), required=False,
                initial=only.get(key), query_params={'site_id': '$site'} if key in ('location', 'rack') else None,
            )
            self.value_fields.append(key)
