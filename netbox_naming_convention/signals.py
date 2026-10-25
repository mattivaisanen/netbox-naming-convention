"""
Save hooks for the objects rules name (devices, virtual machines, racks;
see kinds.py). "Device" below stands for any of them.

- post_clean (NetBox sends it from every model's clean(), so it runs for the
  web UI, CSV import and the REST API's validation): a new device without a
  name gets the rule's suggestion, so NetBox's own checks (unique names per
  site) see it; a name typed by hand is checked when the rule refuses names
  that don't fit. Virtual machines and racks must have a name, so a rule
  that can't name one yet is a validation error.
- pre_save: the number is picked again under the series lock, inside the
  save's transaction, and remembered as handed out. Also catches code that
  saves without validating (scripts, NetBox setting a primary IP), so a
  device without a name is named as soon as its rule has what it needs.
  The change log entry's message says the name came from the rule.
- post_save: remembers which names a rule gave (AssignedName), for the
  device page and change requests, and uses up a reservation of the name
  (ReservedName). post_delete forgets the names a rule gave.

A device that has a name is never renamed here: renaming is always a person's
edit (the device form's "Suggest again" button).
"""
import logging

from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, post_save, pre_save

from netbox.context import current_request
from netbox.signals import post_clean
from utilities.exceptions import AbortRequest

from . import naming
from .kinds import KINDS, kind_of
from .matching import find_rule
from .models import AssignedHowChoices, AssignedName, EnforcementChoices, ReservedName

logger = logging.getLogger('netbox_naming_convention')


def _stored_name(obj):
    if obj._state.adding or not obj.pk:
        return None
    return type(obj).objects.filter(pk=obj.pk).values_list('name', flat=True).first()


def _form_value(key):
    """A value the device form posted, or None (also for the REST API)."""
    request = current_request.get()
    if request is None or request.method != 'POST':
        return None
    if request.content_type not in ('application/x-www-form-urlencoded', 'multipart/form-data'):
        return None
    try:
        return request.POST.get(key)
    except Exception:  # noqa: BLE001 - a body someone else already read
        return None


def _form_says_auto(instance):
    """
    The device add form shows the rule's name in the grayed-out field and
    sends `_naming_auto=1` with it: that name is the plugin's, not typed, so
    the number is picked again at save (someone may have taken it).
    """
    return instance._state.adding and _form_value('_naming_auto') == '1'


def _accepted_suggestion(instance, rule):
    """
    Editing: the user pressed "Suggest again" (the form sends the suggested
    name as `_naming_suggested`) and saves that name, or renamed devices from
    the rule page (`_naming_rename`, through NetBox's device import). Remembered as given by
    the rule, so the change request shows it, even while the rename waits for
    approval.
    """
    if instance._state.adding or not instance.name:
        return
    if _form_value('_naming_suggested') != instance.name and _form_value('_naming_rename') != '1':
        return
    if instance.name == _stored_name(instance):
        return
    suggestion = naming.suggest(instance, rule)
    if suggestion.ready and suggestion.name == instance.name:
        AssignedName.record(instance, instance.name, rule, AssignedHowChoices.SUGGESTED)
        # The view sets the change log message after validation; pre_save adds ours.
        instance._naming_suggested_by = rule


def name_on_clean(sender, instance, **kwargs):
    if getattr(instance, '_naming_skip', False):
        return
    if instance.name and _form_says_auto(instance):
        instance.name = None
    rule = find_rule(instance)
    if rule is None:
        return
    if not instance.name:
        suggestion = naming.suggest(instance, rule, keep_current=False)
        if suggestion.error:
            raise ValidationError({'name': suggestion.error})
        if suggestion.ready:
            instance.name = suggestion.name
            naming.mark_auto(instance)
        elif rule.kind.name_required or (
            rule.enforcement == EnforcementChoices.REFUSE and suggestion.missing != ['primary IP']
        ):
            raise ValidationError({'name': _waiting(rule, suggestion)})
        return
    if naming.is_auto(instance):
        return
    _accepted_suggestion(instance, rule)
    if rule.enforcement != EnforcementChoices.REFUSE:
        return
    if instance._state.adding or instance.name != _stored_name(instance):
        error = naming.check_typed_name(instance, rule)
        if error:
            raise ValidationError({'name': error})


def _waiting(rule, suggestion):
    kind = rule.kind.label.lower()
    return f'The rule "{rule}" names this {kind} once it has: {", ".join(suggestion.missing)}.'


def name_on_save(sender, instance, raw=False, **kwargs):
    if raw or getattr(instance, '_naming_skip', False):
        return
    if instance.name and not naming.is_auto(instance):
        # A name someone gave: only remember its number.
        if instance._state.adding or instance.name != _stored_name(instance):
            naming.remember(instance)
        suggested_by = getattr(instance, '_naming_suggested_by', None)
        if suggested_by is not None:
            instance._naming_suggested_by = None
            _add_changelog_message(instance, _message(suggested_by, AssignedHowChoices.SUGGESTED))
        return
    rule = find_rule(instance)
    if rule is None:
        naming.unmark_auto(instance)
        return
    provisional = instance.name
    naming.unmark_auto(instance)
    suggestion = naming.assign(instance, rule)
    if not suggestion.ready:
        if provisional:
            # Validation filled in a name, but its number can't be taken now
            # (the series filled up, or the IP's number was taken meanwhile).
            # Saving the name anyway would hand out a number twice. NetBox's
            # views, import and API show AbortRequest as an ordinary error.
            raise AbortRequest(suggestion.error or _waiting(rule, suggestion))
        # A device saved without a name, often without validating (NetBox
        # setting a primary IP): it stays unnamed, as NetBox would leave it.
        if suggestion.error:
            logger.warning(
                '%s %s not named by rule "%s": %s', rule.kind.label, instance.pk or '(new)', rule, suggestion.error,
            )
        return
    if provisional and provisional != instance.name:
        logger.info('%s named %s instead of %s: the number was taken meanwhile.', rule.kind.label, instance.name,
                    provisional)
    instance._naming_assigned = rule
    _add_changelog_message(instance, _message(rule, AssignedHowChoices.AUTO))


def record_on_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    if instance.name:
        # The reserved name is in use now.
        ReservedName.objects.filter(object_type=kind_of(instance).key, name__iexact=instance.name).delete()
    rule = getattr(instance, '_naming_assigned', None)
    if rule is None:
        return
    instance._naming_assigned = None
    AssignedName.record(instance, instance.name, rule, AssignedHowChoices.AUTO)


def forget_on_delete(sender, instance, **kwargs):
    AssignedName.of(instance).delete()


def connect():
    """Hook the save signals of every kind's model (called from the app's ready())."""
    for kind in KINDS.values():
        model = kind.model
        uid = f'netbox_naming_convention.{kind.key}'
        post_clean.connect(name_on_clean, sender=model, dispatch_uid=f'{uid}.clean')
        pre_save.connect(name_on_save, sender=model, dispatch_uid=f'{uid}.pre_save')
        post_save.connect(record_on_save, sender=model, dispatch_uid=f'{uid}.post_save')
        post_delete.connect(forget_on_delete, sender=model, dispatch_uid=f'{uid}.post_delete')


def _message(rule, how):
    if how == AssignedHowChoices.AUTO:
        return f'Name from naming rule "{rule}"'
    return f'Name suggested by naming rule "{rule}"'


def _add_changelog_message(instance, text):
    """Add `text` to the message of the change log entry, after any typed one."""
    typed = getattr(instance, '_changelog_message', None) or ''
    if text in typed:
        return
    combined = f'{typed} | {text}' if typed else text
    instance._changelog_message = combined if len(combined) <= 200 else combined[:199] + '\u2026'
