from django.urls import reverse

from dcim.models import Device
from netbox.plugins import PluginTemplateExtension

from .matching import find_rule, rules_queryset
from .models import AssignedName
from .naming import _number_of, follows, suggest
from .settings import get_setting

#: The device pages that get the form helper (the name field script).
DEVICE_FORM_VIEWS = {'dcim:device_add': 'add', 'dcim:device_edit': 'edit'}


class DeviceNamingPanel(PluginTemplateExtension):
    """On a device: its rule, whether its name follows it, and the suggestion if not."""
    models = ('dcim.device',)

    def right_page(self):
        device = self.context['object']
        rule = find_rule(device)
        if rule is None:
            return ''
        _rule, fits = follows(device, rule)
        result = suggest(device, rule)
        number = _number_of(device.name, result.prefix, result.suffix, 'name') if result.series else None
        return self.render('netbox_naming_convention/inc/device_panel.html', extra_context={
            'rule': rule, 'fits': fits, 'suggestion': result, 'number': number,
            'number_text': rule.format_number(number) if number is not None else '',
            'assigned': AssignedName.lookup(device.pk, device.name),
        })


class DeviceFormHelper(PluginTemplateExtension):
    """
    The device add and edit forms get a small script (inc/device_form.html):
    on add, the name is grayed out and shows the rule's name; on edit, a
    name that follows its rule is grayed out too, and a "Suggest again"
    button appears when the values the name is built from change.
    models=None because head() is only offered for every page.
    """
    def head(self):
        request = self.context.get('request')
        if request is None or not get_setting('device_form'):
            return ''
        match = getattr(request, 'resolver_match', None)
        mode = DEVICE_FORM_VIEWS.get(match.view_name if match else None)
        if mode is None:
            return ''
        if not rules_queryset().exists():
            return ''
        locked = mode == 'add'
        device = None
        if mode == 'edit':
            # head() gets no object in its context; the page's URL has it.
            device = Device.objects.restrict(request.user, 'view').filter(pk=match.kwargs.get('pk')).first()
            if device is None:
                return ''
            _rule, fits = follows(device)
            # A name the rule gave is grayed out like on add; others are left alone.
            locked = bool(fits)
        return self.render('netbox_naming_convention/inc/device_form.html', extra_context={
            'naming_mode': mode,
            'naming_device': device.pk if device else '',
            'naming_locked': 'yes' if locked else '',
            'naming_url': reverse('plugins-api:netbox_naming_convention-api:suggest'),
        })


class ChangeRequestNaming(PluginTemplateExtension):
    """
    netbox-change-approval's change request page: says when a device's new
    name was given by a naming rule. Only matches when that plugin is
    installed (the model label is just a string here).
    """
    models = ('netbox_change_approval.changerequest',)

    def alerts(self):
        change = self.context.get('object')
        if change is None or change.content_type.app_label != 'dcim' or change.content_type.model != 'device':
            return ''
        diff = change.diff if isinstance(change.diff, dict) else {}
        name = diff.get('name')
        if isinstance(name, dict):
            name = name.get('new')
        if not name or not isinstance(name, str):
            return ''
        assigned = AssignedName.lookup(change.object_id, name)
        if assigned is None:
            return ''
        return self.render('netbox_naming_convention/inc/change_request_alert.html', extra_context={
            'assigned': assigned,
        })


template_extensions = [DeviceNamingPanel, DeviceFormHelper, ChangeRequestNaming]
