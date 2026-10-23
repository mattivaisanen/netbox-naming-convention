import django_filters
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from dcim.models import DeviceRole, DeviceType, Site
from netbox.filtersets import NetBoxModelFilterSet

from .models import EnforcementChoices, NamingRule, NumberSourceChoices


class NamingRuleFilterSet(NetBoxModelFilterSet):
    role_id = django_filters.ModelMultipleChoiceFilter(
        field_name='roles', queryset=DeviceRole.objects.all(), label=_('Role (ID)'),
    )
    device_type_id = django_filters.ModelMultipleChoiceFilter(
        field_name='device_types', queryset=DeviceType.objects.all(), label=_('Device type (ID)'),
    )
    site_id = django_filters.ModelMultipleChoiceFilter(
        field_name='sites', queryset=Site.objects.all(), label=_('Site (ID)'),
    )
    number_source = django_filters.MultipleChoiceFilter(choices=NumberSourceChoices)
    enforcement = django_filters.MultipleChoiceFilter(choices=EnforcementChoices)

    class Meta:
        model = NamingRule
        fields = ('id', 'name', 'enabled', 'priority', 'template', 'fill_gaps', 'number_scope', 'description')

    def search(self, queryset, name, value):
        if not value.strip():
            return queryset
        return queryset.filter(
            Q(name__icontains=value) | Q(template__icontains=value) | Q(description__icontains=value)
        )
