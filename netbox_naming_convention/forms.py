from django import forms
from django.utils.translation import gettext_lazy as _

from dcim.choices import DeviceStatusChoices
from dcim.models import DeviceRole, DeviceType, Location, Platform, Region, Site, SiteGroup
from extras.models import Tag
from netbox.forms import NetBoxModelFilterSetForm, NetBoxModelForm
from tenancy.models import Tenant
from utilities.forms.fields import (
    CommentField, DynamicModelMultipleChoiceField, JSONField, TagFilterField,
)
from utilities.forms.rendering import FieldSet

from .models import EnforcementChoices, NamingRule, NumberSourceChoices


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
    match_tags = DynamicModelMultipleChoiceField(
        label=_('Device tags'), queryset=Tag.objects.all(), required=False,
        help_text=_('Tags the device must have (for example "ot").'),
    )
    constraint = JSONField(label=_('Advanced condition'), required=False)
    comments = CommentField()

    fieldsets = (
        FieldSet('name', 'description', 'enabled', 'priority', 'tags', name=_('Rule')),
        FieldSet('roles', 'device_types', name=_('Kind of device (one of these is required)')),
        FieldSet(
            'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms', 'statuses', 'match_tags',
            'tag_match', 'constraint', name=_('Other conditions (optional)'),
        ),
        FieldSet('template', name=_('Name')),
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
            'template', 'number_source', 'ip_pattern', 'number_digits', 'number_first', 'number_last',
            'skip_numbers', 'fill_gaps', 'number_scope', 'enforcement', 'comments', 'tags',
        )
        widgets = {
            'template': forms.TextInput(attrs={'class': 'font-monospace'}),
        }

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
