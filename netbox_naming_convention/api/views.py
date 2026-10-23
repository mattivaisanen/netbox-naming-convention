from django.utils.translation import gettext as _
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import APIRootView
from rest_framework.views import APIView

from dcim.models import Device, DeviceRole, DeviceType, Location, Platform, Rack, Site
from extras.models import Tag
from ipam.models import IPAddress
from netbox.api.viewsets import NetBoxModelViewSet
from tenancy.models import Tenant

from .. import filtersets
from ..models import NamingRule
from ..naming import suggest
from . import serializers


class NamingConventionRootView(APIRootView):
    def get_view_name(self):
        return 'Naming convention'


class NamingRuleViewSet(NetBoxModelViewSet):
    queryset = NamingRule.objects.prefetch_related(
        'roles', 'device_types', 'regions', 'site_groups', 'sites', 'locations', 'tenants', 'platforms',
        'match_tags', 'tags',
    )
    serializer_class = serializers.NamingRuleSerializer
    filterset_class = filtersets.NamingRuleFilterSet


#: Form fields that point at another object, and that object's model.
RELATED = {
    'site': Site,
    'location': Location,
    'rack': Rack,
    'role': DeviceRole,
    'device_type': DeviceType,
    'tenant': Tenant,
    'platform': Platform,
    'primary_ip4': IPAddress,
    'primary_ip6': IPAddress,
}


def device_from_values(user, values):
    """
    An unsaved Device carrying the form's values. Objects the user may not
    view are left out, so the answer never shows their names.
    """
    pk = values.get('device')
    if pk:
        device = Device.objects.restrict(user, 'view').filter(pk=pk).first()
        if device is None:
            return None
    else:
        device = Device()
    for key, model in RELATED.items():
        if key not in values:
            continue
        value = values[key]
        if value and not model.objects.restrict(user, 'view').filter(pk=value).exists():
            value = None
        setattr(device, f'{key}_id', value)
        # Drop a cached object of the old value.
        device._state.fields_cache.pop(key, None)
    for key in ('status', 'serial', 'asset_tag', 'name'):
        if key in values:
            setattr(device, key, values[key] or ('' if key == 'serial' else None))
    if 'custom_fields' in values:
        device.custom_field_data = {**(device.custom_field_data or {}), **values['custom_fields']}
    if 'tags' in values:
        tags = list(Tag.objects.restrict(user, 'view').filter(pk__in=values['tags']))
        device._m2m_values = {'tags': tags}
    return device


class SuggestView(APIView):
    """
    POST the device form's values; get the rule that matches, the name it
    suggests, and what it still waits for. Saves and reserves nothing.
    """
    permission_classes = [IsAuthenticated]

    def get_view_name(self):
        return 'Suggest a device name'

    def post(self, request):
        user = request.user
        if not (user.has_perm('dcim.add_device') or user.has_perm('dcim.change_device')):
            raise PermissionDenied(_('Suggesting names needs permission to add or change devices.'))
        serializer = serializers.SuggestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        device = device_from_values(user, values)
        if device is None:
            return Response({'detail': _('Device not found.')}, status=status.HTTP_404_NOT_FOUND)
        result = suggest(device, keep_current=bool(values.get('device')))
        data = result.as_dict()
        data['current'] = device.name or None
        return Response(data)
