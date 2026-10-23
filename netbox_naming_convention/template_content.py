from django.urls import reverse

from netbox.plugins import PluginTemplateExtension

from .matching import find_rule
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
        })


class DeviceFormHelper(PluginTemplateExtension):
    """
    The device add and edit forms get a small script (inc/device_form.html):
    on add, the name is grayed out and shows the rule's name; on edit, a
    "Suggest again" button appears when the values the name is built from
    change. models=None because head() is only offered for every page.
    """
    def head(self):
        request = self.context.get('request')
        if request is None or not get_setting('device_form'):
            return ''
        match = getattr(request, 'resolver_match', None)
        mode = DEVICE_FORM_VIEWS.get(match.view_name if match else None)
        if mode is None:
            return ''
        device_pk = match.kwargs.get('pk') if mode == 'edit' else None
        return self.render('netbox_naming_convention/inc/device_form.html', extra_context={
            'naming_mode': mode,
            'naming_device': device_pk or '',
            'naming_url': reverse('plugins-api:netbox_naming_convention-api:suggest'),
        })


template_extensions = [DeviceNamingPanel, DeviceFormHelper]
