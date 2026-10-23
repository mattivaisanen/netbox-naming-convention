"""Plugin settings: PLUGINS_CONFIG['netbox_naming_convention'], with defaults
from NamingConventionConfig.default_settings."""
from netbox.plugins.utils import get_plugin_config

PLUGIN = 'netbox_naming_convention'


def get_setting(key):
    return get_plugin_config(PLUGIN, key)
