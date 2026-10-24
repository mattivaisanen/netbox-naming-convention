from django import forms
from django.urls import reverse
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from dcim.choices import DeviceStatusChoices
from dcim.models import Device, DeviceRole, DeviceType, Location, Platform, Region, Site, SiteGroup
from extras.models import Tag
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from tenancy.models import Tenant
from utilities.forms.fields import (
    CommentField, DynamicModelChoiceField, DynamicModelMultipleChoiceField, JSONField, TagFilterField,
)
from utilities.forms.rendering import FieldSet
from utilities.forms.utils import get_field_value
from utilities.forms.widgets import APISelect, HTMXSelect

from .models import EnforcementChoices, NamingRule, NumberSourceChoices, RequiredValueChoices


class PreviewDeviceSelect(APISelect):
    """
    The device picker of the rule form's preview, with the preview below it:
    the template posts the whole form to the preview view whenever it
    changes (see preview.py).
    """
    template_name = 'netbox_naming_convention/inc/preview_device.html'
    preview_url = ''

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context['preview_url'] = self.preview_url
        return context


class NamingRuleForm(NetBoxModelForm):
    roles = DynamicModelMultipleChoiceField(label=_('Roles'), queryset=DeviceRole.objects.all(), required=False)
    device_types = DynamicModelMultipleChoiceField(
        label=_('Device types'), queryset=DeviceType.objects.all(), required=False,
    )
    regions = DynamicModelMultipleChoiceField(label=_('Regions'), queryset=Region.objects.all(), required=False)
    site_groups = DynamicModelMultipleChoiceField(
        label=_('Site groups'), queryset=SiteGroup.objects.all(), required=False,
    )
    sites = DynamicModelMultipleChoiceField(label=_('Sites'), queryset=Site.objects.all(), required=False)
    locations = DynamicModelMultipleChoiceField(
        label=_('Locations'), queryset=Location.objects.all(), required=False,
    )
    tenants = DynamicModelMultipleChoiceField(label=_('Tenants'), queryset=Tenant.objects.all(), required=False)
    platforms = DynamicModelMultipleChoiceField(
        label=_('Platforms'), queryset=Platform.objects.all(), required=False,
    )
    statuses = forms.MultipleChoiceField(label=_('Statuses'), choices=DeviceStatusChoices, required=False)
    required_values = forms.MultipleChoiceField(
        label=_('Wait for'), choices=RequiredValueChoices, required=False,
        help_text=NamingRule._meta.get_field('required_values').help_text,
    )
    match_tags = DynamicModelMultipleChoiceField(
        label=_('Device tags'), queryset=Tag.objects.all(), required=False,
        help_text=_('Tags the device must have.'),
    )
    constraint = JSONField(label=_('Advanced condition'), required=False)
    comments = CommentField()
    # Not saved: only for the preview.
    preview_device = DynamicModelChoiceField(
        label=_('Try on device'), queryset=Device.objects.all(), required=False, widget=PreviewDeviceSelect,
    )

    fieldsets = (
        FieldSet('name', 'description', 'enabled', 'priority', 'tags', name=_('Rule')),
        FieldSet('roles', 'device_types', name=_('Kind of device (one of these is required)')),
        FieldSet(
            'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms', 'statuses', 'match_tags',
            'tag_match', 'constraint', name=_('Other conditions (optional)'),
        ),
        FieldSet('template', 'name_filters', 'required_values', name=_('Name')),
        FieldSet('preview_device', name=_('Preview')),
        FieldSet(
            'number_source', 'number_digits', 'number_first', 'number_last', 'skip_numbers', 'fill_gaps',
            'number_scope', 'ip_pattern', name=_('Number'),
        ),
        FieldSet('enforcement', name=_('Enforcement')),
    )

    class Meta:
        model = NamingRule
        fields = (
            'name', 'description', 'enabled', 'priority', 'roles', 'device_types', 'regions', 'site_groups',
            'sites', 'locations', 'tenants', 'platforms', 'statuses', 'match_tags', 'tag_match', 'constraint',
            'template', 'name_filters', 'required_values', 'number_source', 'ip_pattern', 'number_digits',
            'number_first', 'number_last', 'skip_numbers', 'fill_gaps', 'number_scope', 'enforcement', 'comments',
            'tags',
        )
        widgets = {
            'template': forms.TextInput(attrs={'class': 'font-monospace'}),
            'name_filters': forms.TextInput(attrs={'class': 'font-monospace'}),
            # Changing the source draws the form again with its own fields.
            'number_source': HTMXSelect(),
        }

    #: Fields that mean nothing for the other number source.
    SEQUENCE_ONLY = ('number_first', 'number_last', 'skip_numbers', 'fill_gaps')
    IP_ONLY = ('ip_pattern',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['template'].help_text = format_html(
            '{} <a href="{}" target="_blank">{}</a>',
            self.fields['template'].help_text,
            reverse('plugins:netbox_naming_convention:reference'),
            _('All values and filters'),
        )
        url = reverse('plugins:netbox_naming_convention:namingrule_preview')
        self.fields['preview_device'].widget.preview_url = f'{url}?rule={self.instance.pk}' if self.instance.pk else url
        source = get_field_value(self, 'number_source') or NumberSourceChoices.SEQUENCE
        for name in self.IP_ONLY if source == NumberSourceChoices.SEQUENCE else self.SEQUENCE_ONLY:
            del self.fields[name]

    def clean(self):
        super().clean()
        data = self.cleaned_data
        if not data.get('roles') and not data.get('device_types'):
            raise forms.ValidationError({
                'roles': _('A rule needs at least one role or device type.'),
            })
        return data


class NamingRuleFilterForm(NetBoxModelFilterSetForm):
    model = NamingRule
    fieldsets = (
        FieldSet('q', 'filter_id', 'tag'),
        FieldSet('enabled', 'role_id', 'device_type_id', 'site_id', 'number_source', 'enforcement',
                 name=_('Rule')),
    )
    enabled = forms.NullBooleanField(
        required=False, label=_('Enabled'),
        widget=forms.Select(choices=((None, '---------'), (True, _('Yes')), (False, _('No')))),
    )
    role_id = DynamicModelMultipleChoiceField(queryset=DeviceRole.objects.all(), required=False, label=_('Role'))
    device_type_id = DynamicModelMultipleChoiceField(
        queryset=DeviceType.objects.all(), required=False, label=_('Device type'),
    )
    site_id = DynamicModelMultipleChoiceField(queryset=Site.objects.all(), required=False, label=_('Site'))
    number_source = forms.MultipleChoiceField(choices=NumberSourceChoices, required=False, label=_('Number source'))
    enforcement = forms.MultipleChoiceField(choices=EnforcementChoices, required=False, label=_('Enforcement'))
    tag = TagFilterField(model)
