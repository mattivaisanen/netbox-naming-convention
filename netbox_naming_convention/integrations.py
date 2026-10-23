"""
Optional integrations. netbox-change-approval needs no code of its own here:
naming rules are NetBoxModels, so it gates them like any object, and the
plugin's bookkeeping (NamingSeries) is not a NetBoxModel, so it is never
gated. A new device is written at once by change-approval (marked pending),
so its name and number are taken like any other; a rename from "Suggest
again" is an ordinary edit and waits for approval. Nothing here imports
another plugin.
"""
from django.apps import apps

CHANGE_APPROVAL = 'netbox_change_approval'


def has_change_approval():
    return apps.is_installed(CHANGE_APPROVAL)
