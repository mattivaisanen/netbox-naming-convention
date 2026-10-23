"""
Device save hooks.

- post_clean (NetBox sends it from every model's clean(), so it runs for the
  web UI, CSV import and the REST API's validation): a new device without a
  name gets the rule's suggestion, so NetBox's own checks (unique names per
  site) see it; a name typed by hand is checked when the rule refuses names
  that don't fit.
- pre_save: the number is picked again under the series lock, inside the
  save's transaction, and remembered as handed out. Also catches code that
  saves without validating (scripts, NetBox setting a primary IP), so a
  device without a name is named as soon as its rule has what it needs.

A device that has a name is never renamed here: renaming is always a person's
edit (the device form's "Suggest again" button).
"""
import logging

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.dispatch import receiver

from dcim.models import Device
from netbox.context import current_request
from netbox.signals import post_clean

from . import naming
from .matching import find_rule
from .models import EnforcementChoices

logger = logging.getLogger('netbox_naming_convention')


def _stored_name(device):
    if device._state.adding or not device.pk:
        return None
    return Device.objects.filter(pk=device.pk).values_list('name', flat=True).first()


def _form_says_auto(instance):
    """
    The device add form shows the rule's name in the grayed-out field and
    sends `_naming_auto=1` with it: that name is the plugin's, not typed, so
    the number is picked again at save (someone may have taken it).
    """
    if not instance._state.adding:
        return False
    request = current_request.get()
    if request is None or request.method != 'POST':
        return False
    if request.content_type not in ('application/x-www-form-urlencoded', 'multipart/form-data'):
        return False
    try:
        return request.POST.get('_naming_auto') == '1'
    except Exception:  # noqa: BLE001 - a body someone else already read
        return False


@receiver(post_clean, sender=Device)
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
        elif rule.enforcement == EnforcementChoices.REFUSE and suggestion.missing != ['primary IP']:
            raise ValidationError({'name': _waiting(rule, suggestion)})
        return
    if naming.is_auto(instance) or rule.enforcement != EnforcementChoices.REFUSE:
        return
    if instance._state.adding or instance.name != _stored_name(instance):
        error = naming.check_typed_name(instance, rule)
        if error:
            raise ValidationError({'name': error})


def _waiting(rule, suggestion):
    return f'The rule "{rule}" names this device once it has: {", ".join(suggestion.missing)}.'


@receiver(pre_save, sender=Device)
def name_on_save(sender, instance, raw=False, **kwargs):
    if raw or getattr(instance, '_naming_skip', False):
        return
    if instance.name and not naming.is_auto(instance):
        # A name someone gave: only remember its number.
        if instance._state.adding or instance.name != _stored_name(instance):
            naming.remember(instance)
        return
    rule = find_rule(instance)
    if rule is None:
        naming.unmark_auto(instance)
        return
    provisional = instance.name
    naming.unmark_auto(instance)
    suggestion = naming.assign(instance, rule)
    if not suggestion.ready:
        # Leave it as it was: validation already said what is wrong, and code
        # that saves without validating gets NetBox's normal behaviour.
        instance.name = provisional or instance.name
        if suggestion.error:
            logger.warning('Device %s not named by rule "%s": %s', instance.pk or '(new)', rule, suggestion.error)
        return
    if provisional and provisional != instance.name:
        logger.info('Device named %s instead of %s: the number was taken meanwhile.', instance.name, provisional)
