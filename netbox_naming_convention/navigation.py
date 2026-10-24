from django.utils.translation import gettext_lazy as _

from netbox.plugins import PluginMenu, PluginMenuButton, PluginMenuItem

menu = PluginMenu(
    label=_('Naming'),
    icon_class='mdi mdi-format-letter-case',
    groups=(
        (_('Naming'), (
            PluginMenuItem(
                link='plugins:netbox_naming_convention:namingrule_list',
                link_text=_('Naming rules'),
                permissions=['netbox_naming_convention.view_namingrule'],
                buttons=(
                    PluginMenuButton(
                        link='plugins:netbox_naming_convention:namingrule_add',
                        title=_('Add'),
                        icon_class='mdi mdi-plus-thick',
                        permissions=['netbox_naming_convention.add_namingrule'],
                    ),
                ),
            ),
            PluginMenuItem(
                link='plugins:netbox_naming_convention:report',
                link_text=_('Naming report'),
            ),
        )),
    ),
)
