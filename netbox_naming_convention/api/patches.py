"""
Wrapped NetBox internals: `validate` of the device, virtual machine and rack
serializers, and `get_fields` of the virtual machine and rack serializers.

NetBox's REST API validates a *copy* of the object (ValidatedModelSerializer
builds an instance from the request, runs full_clean() on it, and then
creates the real object from the request data). The name our post_clean
hook fills in on the copy would be lost, so before NetBox's own validation
this puts the rule's name into the data for a new object sent without one,
and marks it as filled in by the plugin (signals.py picks the number again
under the lock when the object is saved).

Virtual machines and racks must have a name, so their serializers require
one. On create the name is made optional; without a rule that can name the
object, NetBox's own validation still refuses the missing name.
"""
from dcim.api.serializers import DeviceSerializer, RackSerializer
from virtualization.api.serializers import VirtualMachineSerializer

#: Serializers wrapped, and whether their name is made optional on create.
SERIALIZERS = {
    DeviceSerializer: False,
    VirtualMachineSerializer: True,
    RackSerializer: True,
}

_applied = False


def _object_from_data(serializer, data):
    model = serializer.Meta.model
    attrs = dict(data)
    opts = model._meta
    m2m = {}
    for field in [*opts.local_many_to_many, *opts.related_objects]:
        if field.name in attrs:
            m2m[field.name] = attrs.pop(field.name)
    obj = model(**attrs)
    obj._m2m_values = m2m
    return obj


def _wrap_validate(original):
    def validate(self, data):
        if not (getattr(self, 'nested', False) or self.instance is not None or data.get('name')):
            from ..naming import mark_auto, suggest

            obj = _object_from_data(self, data)
            result = suggest(obj, keep_current=False)
            if result.ready:
                data['name'] = result.name
                obj.name = result.name
                mark_auto(obj)
        return original(self, data)
    return validate


def _wrap_get_fields(original):
    def get_fields(self):
        fields = original(self)
        if self.instance is None and 'name' in fields:
            fields['name'].required = False
        return fields
    return get_fields


def apply():
    global _applied
    if _applied:
        return
    _applied = True
    for serializer, optional_name in SERIALIZERS.items():
        serializer.validate = _wrap_validate(serializer.validate)
        if optional_name:
            serializer.get_fields = _wrap_get_fields(serializer.get_fields)
