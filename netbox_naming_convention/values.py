"""
Unsaved objects built from the values an object form (or the API) sends,
so a rule can be matched and a name suggested before anything is saved.
"""
from extras.models import Tag

__all__ = ('object_from_values',)


def object_from_values(user, kind, values):
    """
    An unsaved object of `kind` carrying the form's values (or a saved one
    with them applied, for `id`). Objects the user may not view are left
    out, so the answer never shows their names. None when `id` is not found.
    """
    model = kind.model
    pk = values.get('id')
    if pk:
        obj = model.objects.restrict(user, 'view').filter(pk=pk).first()
        if obj is None:
            return None
    else:
        obj = model()
    for key in kind.form_fields:
        if key not in values:
            continue
        value = values[key]
        field = model._meta.get_field(key)
        if field.is_relation:
            related = field.related_model
            if value and not related.objects.restrict(user, 'view').filter(pk=value).exists():
                value = None
            setattr(obj, field.attname, value or None)
            # Drop a cached object of the old value.
            obj._state.fields_cache.pop(key, None)
        else:
            setattr(obj, key, value or ('' if not field.null else None))
    if 'name' in values:
        obj.name = values['name'] or ('' if not model._meta.get_field('name').null else None)
    if 'custom_fields' in values:
        obj.custom_field_data = {**(obj.custom_field_data or {}), **values['custom_fields']}
    if 'tags' in values:
        tags = list(Tag.objects.restrict(user, 'view').filter(pk__in=values['tags']))
        obj._m2m_values = {'tags': tags}
    return obj
