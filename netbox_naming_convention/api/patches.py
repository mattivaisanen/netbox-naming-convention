"""
One NetBox internal is wrapped: DeviceSerializer.validate.

NetBox's REST API validates a *copy* of the device (ValidatedModelSerializer
builds an instance from the request, runs full_clean() on it, and then
creates the real device from the request data). The name our post_clean
hook fills in on the copy would be lost, so after NetBox's own validation
this puts the rule's name into the data for a new device sent without one,
and marks it as filled in by the plugin (signals.py picks the number again
under the lock when the device is saved).
"""
from dcim.api.serializers import DeviceSerializer

_original = None


def _device_from_data(serializer, data):
    from dcim.models import Device

    attrs = dict(data)
    opts = Device._meta
    m2m = {}
    for field in [*opts.local_many_to_many, *opts.related_objects]:
        if field.name in attrs:
            m2m[field.name] = attrs.pop(field.name)
    device = Device(**attrs)
    device._m2m_values = m2m
    return device


def _validate(self, data):
    data = _original(self, data)
    if getattr(self, 'nested', False) or self.instance is not None or data.get('name'):
        return data
    from ..naming import mark_auto, suggest

    device = _device_from_data(self, data)
    result = suggest(device, keep_current=False)
    if result.ready:
        data['name'] = result.name
        device.name = result.name
        mark_auto(device)
    return data


def apply():
    global _original
    if _original is not None:
        return
    _original = DeviceSerializer.validate
    DeviceSerializer.validate = _validate
