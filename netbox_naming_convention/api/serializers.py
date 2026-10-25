from rest_framework import serializers

from dcim.api.serializers import (
    DeviceRoleSerializer, DeviceTypeSerializer, LocationSerializer, PlatformSerializer, RackRoleSerializer,
    RackTypeSerializer, RegionSerializer, SiteGroupSerializer, SiteSerializer,
)
from extras.api.serializers import TagSerializer
from netbox.api.fields import ChoiceField, SerializedPKRelatedField
from netbox.api.serializers import NetBoxModelSerializer
from tenancy.api.serializers import TenantSerializer
from virtualization.api.serializers import ClusterSerializer, VirtualMachineTypeSerializer

from dcim.models import DeviceRole, DeviceType, Location, Platform, RackRole, RackType, Region, Site, SiteGroup
from extras.models import Tag
from tenancy.models import Tenant
from virtualization.models import Cluster, VirtualMachineType

from ..kinds import KINDS
from ..models import (
    EnforcementChoices, NamingRule, NumberScopeChoices, NumberSourceChoices, ObjectTypeChoices, ReservedName,
    TagMatchChoices,
)
from ..naming import RESERVE_LIMIT


def _many(model, serializer):
    return SerializedPKRelatedField(
        queryset=model.objects.all(), serializer=serializer, nested=True, required=False, many=True,
    )


class NamingRuleSerializer(NetBoxModelSerializer):
    url = serializers.HyperlinkedIdentityField(view_name='plugins-api:netbox_naming_convention-api:namingrule-detail')
    roles = _many(DeviceRole, DeviceRoleSerializer)
    device_types = _many(DeviceType, DeviceTypeSerializer)
    vm_types = _many(VirtualMachineType, VirtualMachineTypeSerializer)
    clusters = _many(Cluster, ClusterSerializer)
    rack_roles = _many(RackRole, RackRoleSerializer)
    rack_types = _many(RackType, RackTypeSerializer)
    regions = _many(Region, RegionSerializer)
    site_groups = _many(SiteGroup, SiteGroupSerializer)
    sites = _many(Site, SiteSerializer)
    locations = _many(Location, LocationSerializer)
    tenants = _many(Tenant, TenantSerializer)
    platforms = _many(Platform, PlatformSerializer)
    match_tags = _many(Tag, TagSerializer)
    object_type = ChoiceField(choices=ObjectTypeChoices, required=False)
    tag_match = ChoiceField(choices=TagMatchChoices, required=False)
    number_source = ChoiceField(choices=NumberSourceChoices, required=False)
    number_scope = ChoiceField(choices=NumberScopeChoices, required=False)
    enforcement = ChoiceField(choices=EnforcementChoices, required=False)

    class Meta:
        model = NamingRule
        fields = (
            'id', 'url', 'display', 'name', 'description', 'enabled', 'priority', 'object_type', 'roles',
            'device_types', 'vm_types', 'clusters', 'rack_roles', 'rack_types', 'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms', 'statuses', 'match_tags',
            'tag_match', 'constraint', 'template', 'name_filters', 'required_values', 'number_source', 'ip_pattern',
            'number_digits', 'number_first', 'number_last', 'skip_numbers', 'fill_gaps', 'number_scope', 'enforcement',
            'comments', 'tags',
            'custom_fields', 'created', 'last_updated',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'object_type', 'description')

    def validate(self, data):
        data = super().validate(data)
        kind = KINDS.get(data.get('object_type') or getattr(self.instance, 'object_type', None) or 'device')
        if kind is None:
            return data
        values = {}
        for name in NamingRule.CONDITION_FIELDS:
            if name in data:
                values[name] = data[name]
            elif self.instance is not None:
                values[name] = list(getattr(self.instance, name).all())
        if errors := kind.condition_errors(values):
            raise serializers.ValidationError(errors)
        return data


class SuggestSerializer(serializers.Serializer):
    """
    An object form's values (ids), or an object to suggest a new name for
    (`id`; `device` is the same for devices). Unknown keys are ignored, so
    the form can send what it has; keys the object type doesn't have too.
    """
    object_type = ChoiceField(choices=ObjectTypeChoices, required=False)
    id = serializers.IntegerField(required=False, allow_null=True, help_text='An existing object (edit).')
    device = serializers.IntegerField(required=False, allow_null=True, help_text='An existing device (edit).')
    name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    site = serializers.IntegerField(required=False, allow_null=True)
    location = serializers.IntegerField(required=False, allow_null=True)
    rack = serializers.IntegerField(required=False, allow_null=True)
    cluster = serializers.IntegerField(required=False, allow_null=True)
    role = serializers.IntegerField(required=False, allow_null=True)
    device_type = serializers.IntegerField(required=False, allow_null=True)
    virtual_machine_type = serializers.IntegerField(required=False, allow_null=True)
    rack_type = serializers.IntegerField(required=False, allow_null=True)
    tenant = serializers.IntegerField(required=False, allow_null=True)
    platform = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    facility_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    serial = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    asset_tag = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    primary_ip4 = serializers.IntegerField(required=False, allow_null=True)
    primary_ip6 = serializers.IntegerField(required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.IntegerField(), required=False)
    custom_fields = serializers.DictField(required=False)


class ReserveSerializer(SuggestSerializer):
    """What to reserve: the values the names are built from (as for suggest), how many, and for how long."""
    rule = serializers.IntegerField(
        required=False, allow_null=True, help_text='The rule to reserve from. Default: the rule that matches.',
    )
    count = serializers.IntegerField(required=False, default=1, min_value=1, max_value=RESERVE_LIMIT)
    expires = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default='', max_length=200)


class ReservedNameSerializer(serializers.ModelSerializer):
    url = serializers.HyperlinkedIdentityField(
        view_name='plugins-api:netbox_naming_convention-api:reservedname-detail',
    )
    display = serializers.CharField(source='name', read_only=True)
    object_type = ChoiceField(choices=ObjectTypeChoices, read_only=True)
    rule = NamingRuleSerializer(nested=True, read_only=True)

    class Meta:
        model = ReservedName
        fields = (
            'id', 'url', 'display', 'name', 'object_type', 'rule', 'number', 'expires', 'expired', 'description',
            'created_by', 'created',
        )
        brief_fields = ('id', 'url', 'display', 'name', 'object_type')
