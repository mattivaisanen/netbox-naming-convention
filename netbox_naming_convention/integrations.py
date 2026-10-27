"""
Optional integrations. Nothing here imports another plugin.

netbox-change-approval: naming rules are NetBoxModels, so it gates them like
any object, and the plugin's bookkeeping (NamingSeries, AssignedName) is not
a NetBoxModel, so it is never gated. A new device is written at once by
change-approval (marked pending), so its name and number are taken like any
other while the request is open. When the request is rejected, withdrawn,
sent back or expires, change-approval deletes the device; its number is then
given back to the series (see `awaiting_approval()` and naming.release()).
A rename from "Suggest again" is an ordinary edit and waits for approval.
"""
from django.apps import apps
from django.contrib.contenttypes.models import ContentType

CHANGE_APPROVAL = 'netbox_change_approval'


def has_change_approval():
    return apps.is_installed(CHANGE_APPROVAL)


def awaiting_approval(obj):
    """
    True when `obj` was added through netbox-change-approval and its create
    request is still open. Always False without that plugin.
    """
    if not obj.pk or not has_change_approval():
        return False
    change_request = apps.get_model(CHANGE_APPROVAL, 'ChangeRequest')
    return change_request.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=obj.pk, action='create', status='pending',
    ).exists()
