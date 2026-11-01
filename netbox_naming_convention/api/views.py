from django.utils.translation import gettext as _
from rest_framework import mixins, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.routers import APIRootView
from rest_framework.views import APIView

from extras.models import Tag
from netbox.api.viewsets import BaseViewSet, NetBoxModelViewSet

from .. import filtersets
from ..kinds import KINDS
from ..matching import find_rule
from ..models import NamingRule, ReservedName
from ..naming import free_reservations, reserve, suggest
from . import serializers


class NamingConventionRootView(APIRootView):
    def get_view_name(self):
        return 'Naming convention'


class NamingRuleViewSet(NetBoxModelViewSet):
    queryset = NamingRule.objects.prefetch_related(*NamingRule.CONDITION_FIELDS, 'tags')
    serializer_class = serializers.NamingRuleSerializer
    filterset_class = filtersets.NamingRuleFilterSet


class ReservedNameViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, BaseViewSet):
    """Names reserved ahead of time. Reserve with POST reserve/; DELETE frees a name."""
    queryset = ReservedName.objects.select_related('rule')
    serializer_class = serializers.ReservedNameSerializer
    filterset_fields = ('rule', 'object_type', 'name')

    def perform_destroy(self, instance):
        # Its number goes back to the series, as when freed on the rule page.
        free_reservations(ReservedName.objects.filter(pk=instance.pk))


def object_from_values(user, kind, values):
    """
    An unsaved object of `kind` carrying the form's values (or a saved one
    with them applied, for `id`). Objects the user may not view are left
    out, so the answer never shows their names. None when `id` is not found.
    """
    model = kind.model
    pk = values.get('id')
    if pk:
        obj = model.objects.restrict(user, 'view').filter(pk=pk).first()
        if obj is None:
            return None
    else:
        obj = model()
    for key in kind.form_fields:
        if key not in values:
            continue
        value = values[key]
        field = model._meta.get_field(key)
        if field.is_relation:
            related = field.related_model
            if value and not related.objects.restrict(user, 'view').filter(pk=value).exists():
                value = None
            setattr(obj, field.attname, value or None)
            # Drop a cached object of the old value.
            obj._state.fields_cache.pop(key, None)
        else:
            setattr(obj, key, value or ('' if not field.null else None))
    if 'name' in values:
        obj.name = values['name'] or ('' if not model._meta.get_field('name').null else None)
    if 'custom_fields' in values:
        obj.custom_field_data = {**(obj.custom_field_data or {}), **values['custom_fields']}
    if 'tags' in values:
        tags = list(Tag.objects.restrict(user, 'view').filter(pk__in=values['tags']))
        obj._m2m_values = {'tags': tags}
    return obj


def _check_perm(user, kind):
    if not (user.has_perm(kind.permission('add')) or user.has_perm(kind.permission('change'))):
        raise PermissionDenied(_('Suggesting names needs permission to add or change {kinds}.').format(
            kinds=kind.label_plural,
        ))


class SuggestView(APIView):
    """
    POST an object form's values (`object_type`: device, virtualmachine or
    rack); get the rule that matches, the name it suggests, and what it
    still waits for. Saves and reserves nothing.
    """
    permission_classes = [IsAuthenticated]

    def get_view_name(self):
        return 'Suggest a name'

    def post(self, request):
        serializer = serializers.SuggestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        kind = KINDS[values.get('object_type') or 'device']
        if values.get('device') and not values.get('id'):
            values['id'] = values['device']
        user = request.user
        _check_perm(user, kind)
        obj = object_from_values(user, kind, values)
        if obj is None:
            return Response({'detail': _('{kind} not found.').format(kind=kind.label)},
                            status=status.HTTP_404_NOT_FOUND)
        result = suggest(obj, keep_current=bool(values.get('id')))
        data = result.as_dict()
        data['current'] = obj.name or None
        return Response(data)


class ReserveView(APIView):
    """
    POST the values names are built from (like suggest, plus `count`,
    `expires`, `description` and optionally `rule`); the next names are
    reserved. Nobody else gets their numbers until an object is saved with
    the name, the reservation is deleted, or it expires.
    """
    permission_classes = [IsAuthenticated]

    def get_view_name(self):
        return 'Reserve names'

    def post(self, request):
        serializer = serializers.ReserveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        user = request.user
        if not user.has_perm('netbox_naming_convention.add_reservedname'):
            raise PermissionDenied(_('Reserving names needs permission to add reserved names.'))
        rule = None
        if values.get('rule'):
            rule = NamingRule.objects.restrict(user, 'view').filter(pk=values['rule']).first()
            if rule is None:
                return Response({'detail': _('Rule not found.')}, status=status.HTTP_404_NOT_FOUND)
        kind = KINDS[values.get('object_type') or (rule.object_type if rule else 'device')]
        _check_perm(user, kind)
        values.pop('id', None)
        obj = object_from_values(user, kind, values)
        rule = rule or find_rule(obj)
        if rule is None:
            return Response({'detail': _('No rule names this {kind}.').format(kind=kind.label.lower())},
                            status=status.HTTP_400_BAD_REQUEST)
        if rule.kind is not kind:
            return Response({'detail': _('The rule "{rule}" names {kinds}.').format(
                rule=rule, kinds=rule.kind.label_plural)}, status=status.HTTP_400_BAD_REQUEST)
        reservations, error = reserve(
            obj, rule, values['count'], expires=values.get('expires'), description=values['description'], user=user,
        )
        if error:
            return Response({'detail': error}, status=status.HTTP_400_BAD_REQUEST)
        data = serializers.ReservedNameSerializer(reservations, many=True, context={'request': request}).data
        return Response(data, status=status.HTTP_201_CREATED)
