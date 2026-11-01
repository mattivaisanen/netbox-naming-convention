"""
Name devices, virtual machines and racks from rules.

A naming rule names one kind of object. It matches them by conditions (for
devices a role or device type, plus optional site, location, tags and more)
and builds their name from a template such as
``{site.slug|upper}-SW{n}-{rack.name}``. The number is a running number per
series, with per-rule digits, range and gap filling, or it is read from the
object's primary IP. Names are filled in when an object is saved without
one, and suggested on its form. See DEVELOPER.md.
"""
from netbox.plugins import PluginConfig


class NamingConventionConfig(PluginConfig):
    name = 'netbox_naming_convention'
    verbose_name = 'Naming Convention'
    description = 'Name devices, virtual machines and racks from rules, with running numbers per series.'
    version = '0.3.0'
    author = 'Matti'
    base_url = 'naming-convention'
    # Only claim what CI tests (.github/workflows/test.yml).
    min_version = '4.7.0'

    default_settings = {
        # Gray out the name on the device, virtual machine and rack add forms
        # and fill it from the matching rule, with a button to type a name
        # instead. False leaves the forms as NetBox has them (device names are
        # still filled in on save).
        'device_form': True,
    }

    menu = 'navigation.menu'
    template_extensions = 'template_content.template_extensions'

    def ready(self):
        super().ready()
        from . import signals
        from .api import patches

        signals.connect()
        patches.apply()


config = NamingConventionConfig
