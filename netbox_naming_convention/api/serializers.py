from django.utils.translation import gettext as _
from rest_framework import serializers

from dcim.api.serializers import (
    DeviceRoleSerializer, DeviceTypeSerializer, LocationSerializer, PlatformSerializer, RegionSerializer,
    SiteGroupSerializer, SiteSerializer,
)
from extras.api.serializers import TagSerializer
from netbox.api.fields import ChoiceField, SerializedPKRelatedField
from netbox.api.serializers import NetBoxModelSerializer
from tenancy.api.serializers import TenantSerializer

from dcim.models import DeviceRole, DeviceType, Location, Platform, Region, Site, SiteGroup
from extras.models import Tag
from tenancy.models import Tenant

from ..models import EnforcementChoices, NamingRule, NumberScopeChoices, NumberSourceChoices, TagMatchChoices


def _many(model, serializer):
    return SerializedPKRelatedField(
        queryset=model.objects.all(), serializer=serializer, nested=True, required=False, many=True,
    )


class NamingRuleSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='plugins-api:netbox_naming_convention-api:namingrule-detail')
    roles = _many(DeviceRole, DeviceRoleSerializer)
    device_types = _many(DeviceType, DeviceTypeSerializer)
    regions = _many(Region, RegionSerializer)
    site_groups = _many(SiteGroup, SiteGroupSerializer)
    sites = _many(Site, SiteSerializer)
    locations = _many(Location, LocationSerializer)
    tenants = _many(Tenant, TenantSerializer)
    platforms = _many(Platform, PlatformSerializer)
    match_tags = _many(Tag, TagSerializer)
    tag_match = ChoiceField(choices=TagMatchChoices, required=False)
    number_source = ChoiceField(choices=NumberSourceChoices, required=False)
    number_scope = ChoiceField(choices=NumberScopeChoices, required=False)
    enforcement = ChoiceField(choices=EnforcementChoices, required=False)

    class Meta:
        model = NamingRule
        fields = (
            'id', 'url', 'display', 'name', 'description', 'enabled', 'priority', 'roles', 'device_types',
            'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms', 'statuses', 'match_tags',
            'tag_match', 'constraint', 'template', 'name_filters', 'number_source', 'ip_pattern', 'number_digits', 'number_first',
            'number_last', 'skip_numbers', 'fill_gaps', 'number_scope', 'enforcement', 'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'description')

    def validate(self, data):
        data = super().validate(data)
        roles = data.get('roles', None)
        types = data.get('device_types', None)
        if self.instance is not None:
            if roles is None:
                roles = list(self.instance.roles.all())
            if types is None:
                types = list(self.instance.device_types.all())
        if not roles and not types:
            raise serializers.ValidationError({'roles': _('A rule needs at least one role or device type.')})
        return data


class SuggestSerializer(serializers.Serializer):
    """
    The device form's values (ids), or a device to suggest a new name for
    (`device`). Unknown keys are ignored, so the form can send what it has.
    """
    device = serializers.IntegerField(required=False, allow_null=True, help_text='An existing device (edit).')
    name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    site = serializers.IntegerField(required=False, allow_null=True)
    location = serializers.IntegerField(required=False, allow_null=True)
    rack = serializers.IntegerField(required=False, allow_null=True)
    role = serializers.IntegerField(required=False, allow_null=True)
    device_type = serializers.IntegerField(required=False, allow_null=True)
    tenant = serializers.IntegerField(required=False, allow_null=True)
    platform = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    serial = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    asset_tag = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    primary_ip4 = serializers.IntegerField(required=False, allow_null=True)
    primary_ip6 = serializers.IntegerField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    custom_fields = serializers.DictField(required=False)
