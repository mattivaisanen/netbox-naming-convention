import json

from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse

from netbox.plugins import PluginTemplateExtension

from .kinds import KINDS
from .matching import find_rule, rules_queryset
from .models import AssignedName
from .naming import number_in_name, follows, suggest
from .settings import get_setting

#: The add and edit pages that get the form helper (the name field script): view name -> (kind, mode).
FORM_VIEWS = {
    **{kind.add_view: (kind, 'add') for kind in KINDS.values()},
    **{kind.edit_view: (kind, 'edit') for kind in KINDS.values()},
}


class NamingPanel(PluginTemplateExtension):
    """On a device, virtual machine or rack: its rule, whether its name follows it, and the suggestion if not."""
    models = tuple(kind.model_label for kind in KINDS.values())

    def right_page(self):
        obj = self.context['object']
        rule = find_rule(obj)
        if rule is None:
            return ''
        _rule, fits = follows(obj, rule)
        result = suggest(obj, rule)
        number = (
            number_in_name(
                obj.name, result.prefix, result.suffix, 'name', rule.member_suffix, rule.letters, rule.name_match,
            )
            if result.series else None
        )
        return self.render('netbox_naming_convention/inc/naming_panel.html', extra_context={
            'rule': rule, 'fits': fits, 'suggestion': result, 'number': number,
            'number_text': rule.format_number(number) if number is not None else '',
            'assigned': AssignedName.lookup(obj, obj.name),
        })


class NameFormHelper(PluginTemplateExtension):
    """
    The device, virtual machine and rack add and edit forms get a small
    script (inc/name_form.html): on add, the name is grayed out and shows the
    rule's name; on edit, a name that follows its rule is grayed out too,
    and a "Suggest again" button appears when the values the name is built
    from change. models=None because head() is only offered for every page.
    """
    def head(self):
        request = self.context.get('request')
        if request is None or not get_setting('device_form'):
            return ''
        match = getattr(request, 'resolver_match', None)
        kind, mode = FORM_VIEWS.get(match.view_name if match else None, (None, None))
        if kind is None:
            return ''
        if not rules_queryset(kind).exists():
            return ''
        locked = mode == 'add'
        obj = None
        if mode == 'edit':
            # head() gets no object in its context; the page's URL has it.
            obj = kind.model.objects.restrict(request.user, 'view').filter(pk=match.kwargs.get('pk')).first()
            if obj is None:
                return ''
            _rule, fits = follows(obj)
            # A name the rule gave is grayed out like on add; others are left alone.
            locked = bool(fits)
        return self.render('netbox_naming_convention/inc/name_form.html', extra_context={
            'naming_mode': mode,
            'naming_type': kind.key,
            'naming_fields_json': json.dumps(kind.form_fields),
            'naming_kind_fields_json': json.dumps(kind.kind_fields),
            'naming_object': obj.pk if obj else '',
            'naming_locked': 'yes' if locked else '',
            'naming_url': reverse('plugins-api:netbox_naming_convention-api:suggest'),
        })


class ChangeRequestNaming(PluginTemplateExtension):
    """
    netbox-change-approval's change request page: for a new object or a
    rename, says whether the name came from (or follows) its naming rule.
    Only matches when that plugin is installed (the model label is just a
    string here).
    """
    models = ('netbox_change_approval.changerequest',)

    def alerts(self):
        change = self.context.get('object')
        obj = requested_object(change)
        if obj is None or not obj.name:
            return ''
        assigned = AssignedName.lookup(obj, obj.name)
        rule = find_rule(obj)
        if assigned is None and rule is None:
            return ''
        fits = follows(obj, rule)[1] if rule else None
        hint = None
        if rule and not fits:
            # Like the edit form: suggest from the name the object has now.
            requested, obj.name = obj.name, getattr(obj, '_naming_stored_name', obj.name)
            hint = suggest(obj, rule)
            obj.name = requested
        return self.render('netbox_naming_convention/inc/change_request_alert.html', extra_context={
            'assigned': assigned, 'rule': rule, 'fits': fits, 'name': obj.name,
            'suggested': hint.name if hint and hint.ready else None,
        })


def requested_object(change):
    """
    The device, virtual machine or rack as a change request would leave it:
    a pending new object as it is, a pending update with its requested
    values applied (in memory). None for anything else, or when the name
    doesn't change.
    """
    if change is None:
        return None
    kind = KINDS.get(change.content_type.model)
    if kind is None or kind.model_label != f'{change.content_type.app_label}.{change.content_type.model}':
        return None
    if change.object_id is None or change.action not in ('create', 'update'):
        return None
    model = kind.model
    obj = model.objects.filter(pk=change.object_id).first()
    diff = change.diff if isinstance(change.diff, dict) else {}
    if obj is None or change.action == 'create':
        return obj
    if 'name' not in diff:
        return None
    obj._naming_stored_name = obj.name
    for key, value in diff.items():
        value = value.get('new') if isinstance(value, dict) else value
        try:
            field = model._meta.get_field(key[:-3] if key.endswith('_id') else key)
        except FieldDoesNotExist:
            continue
        if field.concrete and not field.many_to_many:
            setattr(obj, field.attname, value)
    obj._state.fields_cache = {}
    return obj


template_extensions = [NamingPanel, NameFormHelper, ChangeRequestNaming]
