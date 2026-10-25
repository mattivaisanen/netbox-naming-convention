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
| `device_form` | bool | `True` | On the device, virtual machine and rack add forms, lock and gray out the name and fill it in from the matching rule, with a button to type a name instead; on the edit form, gray out a name that follows its rule and offer *Suggest again*. `False` leaves the forms as NetBox has them. Device names are still filled in on save either way; virtual machines and racks need a name on their forms then. |

Everything else is set per rule under **Naming → Naming rules** (see the
README).

## Permissions

| Permission | Allows |
| --- | --- |
| `netbox_naming_convention.view_namingrule` | Seeing rules, their series and the objects that don't follow them |
| `netbox_naming_convention.add_namingrule`, `change_namingrule`, `delete_namingrule` | Managing rules |
| `dcim.add_device` or `dcim.change_device` (and the same for virtual machines and racks) | Using the suggest endpoint for that kind of object (the forms use it) |
| `netbox_naming_convention.add_reservedname` | Reserving names (also needs permission to add or change that kind of object) |
| `netbox_naming_convention.view_reservedname`, `delete_reservedname` | Seeing reserved names, freeing them |
| (signed in) | The template reference page (*All values and filters* on the rule form) |

Naming an object needs no permission of its own: it happens as part of
saving it, with the permissions of whoever saves it. The suggest
endpoint only reads objects the user may view.
