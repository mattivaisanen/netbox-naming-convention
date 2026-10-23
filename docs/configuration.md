# Configuration

Settings go in NetBox's `configuration.py`:

```python
PLUGINS_CONFIG = {
    'netbox_naming_convention': {
        'device_form': True,
    },
}
```

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `device_form` | bool | `True` | On the device add form, gray out the name and fill it in from the matching rule, with a button to type a name instead; on the edit form, offer *Suggest again*. `False` leaves the forms as NetBox has them. Names are still filled in on save either way. |

Everything else is set per rule under **Naming → Naming rules** (see the
README).

## Permissions

| Permission | Allows |
| --- | --- |
| `netbox_naming_convention.view_namingrule` | Seeing rules, their series and the devices that don't follow them |
| `netbox_naming_convention.add_namingrule`, `change_namingrule`, `delete_namingrule` | Managing rules |
| `dcim.add_device` or `dcim.change_device` | Using the suggest endpoint (the device form uses it) |

Naming a device needs no permission of its own: it happens as part of
saving the device, with the permissions of whoever saves it. The suggest
endpoint only reads objects the user may view.
