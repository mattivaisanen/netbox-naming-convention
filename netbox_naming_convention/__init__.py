"""
Name devices from rules.

A naming rule matches devices by role or device type (plus optional site,
location, tags and more) and builds their name from a template such as
``FI{site.name|first:2|upper}SWI{n}_{rack.name}``. The number is a running
number per series, with per-rule digits, range and gap filling, or it is read
from the device's primary IP. Names are filled in when a device is saved
without one, and suggested on the device form. See DEVELOPER.md.
"""
from netbox.plugins import PluginConfig


class NamingConventionConfig(PluginConfig):
    name = 'netbox_naming_convention'
    verbose_name = 'Naming Convention'
    description = 'Name devices from rules, with running numbers per series.'
    version = '0.1.0'
    author = 'Matti'
    base_url = 'naming-convention'
    # Only claim what CI tests (.github/workflows/test.yml).
    min_version = '4.7.0'

    default_settings = {
        # Gray out the name on the device add form and fill it from the
        # matching rule, with a button to type a name instead. False leaves
        # the form as NetBox has it (names are still filled in on save).
        'device_form': True,
    }

    menu = 'navigation.menu'
    template_extensions = 'template_content.template_extensions'

    def ready(self):
        super().ready()
        from . import signals  # noqa: F401  (connects the device save hooks)
        from .api import patches

        patches.apply()


config = NamingConventionConfig
