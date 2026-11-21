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
  The change log entry's message says the name came from the rule. A name
  that didn't go through validation (NetBox's bulk rename, scripts, plugins
  that write in bulk) is checked here against a rule that refuses names.
- post_save: remembers which names a rule gave (AssignedName), for the
  device page and change requests, and uses up a reservation of the name
  (ReservedName). post_delete forgets the names a rule gave.
- pre_delete: a device deleted while its create request in
  netbox-change-approval is still open (rejected, withdrawn, sent back,
  expired) was never approved, so its number is given back to the series.
  Without that plugin nothing happens here.
- Deleting a value a rule lists (a site, role, tag, ...): when it was the last
  value of that condition, the rule is disabled. An empty condition means
  "any", so the rule would otherwise start naming objects it was never meant
  for.

A device that has a name is never renamed here: renaming is always a person's
edit (the device form's "Suggest again" button).
"""
import logging

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save
from django.utils.translation import gettext as _

from netbox.context import current_request
from netbox.signals import post_clean
from utilities.exceptions import AbortRequest

from . import integrations, naming
from .kinds import KINDS, kind_of
from .matching import find_rule, forget_rules
from .models import AssignedHowChoices, AssignedName, EnforcementChoices, NamingRule, ReservedName

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
    _check_on_clean(instance)
    # Validated: pre_save needn't check this name again (_refuse_unchecked()).
    instance._naming_checked = instance.name


def _check_on_clean(instance):
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
    return _('The rule "{rule}" names this {kind} once it has: {missing}.').format(
        rule=rule, kind=rule.kind.label.lower(), missing=', '.join(suggestion.missing),
    )


def name_on_save(sender, instance, raw=False, **kwargs):
    if raw or getattr(instance, '_naming_skip', False):
        return
    if instance.name and not naming.is_auto(instance):
        # A name someone gave: only remember its number.
        if instance._state.adding or instance.name != _stored_name(instance):
            _refuse_unchecked(instance)
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


def _refuse_unchecked(instance):
    """
    Backstop for a new or changed name saved without validation: a rule that
    refuses names that don't fit refuses it here too. AbortRequest shows as
    an ordinary error in NetBox's views and API, and stops a script.
    """
    if getattr(instance, '_naming_checked', None) == instance.name:
        return
    rule = find_rule(instance)
    if rule is None or rule.enforcement != EnforcementChoices.REFUSE:
        return
    error = naming.check_typed_name(instance, rule)
    if error:
        raise AbortRequest(error)


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


def release_on_delete(sender, instance, **kwargs):
    if not integrations.awaiting_approval(instance):
        return
    try:
        # A savepoint, so a failure here never breaks the delete itself.
        with transaction.atomic():
            naming.release(instance)
    except Exception:
        logger.exception('Could not give back the number of %s', instance)


def forget_on_delete(sender, instance, **kwargs):
    AssignedName.of(instance).delete()


def note_listing_rules(sender, instance, **kwargs):
    """
    pre_delete of a value rules can list (a site, role, tag, ...): remember
    which enabled rules list it, per condition. Checked in post_delete, once
    the rule's links to it are gone (also when several are deleted at once).
    """
    listing = {}
    for name in _CONDITION_MODELS.get(sender, ()):
        pks = list(NamingRule.objects.filter(enabled=True, **{name: instance}).values_list('pk', flat=True))
        if pks:
            listing[name] = pks
    instance._naming_listing_rules = listing


def disable_emptied_rules(sender, instance, **kwargs):
    """post_delete: disable the rules whose condition lost its last value (see note_listing_rules())."""
    for name, pks in (getattr(instance, '_naming_listing_rules', None) or {}).items():
        emptied = NamingRule.objects.filter(pk__in=pks, enabled=True).annotate(left=Count(name)).filter(left=0)
        for rule in emptied:
            label = NamingRule._meta.get_field(name).verbose_name
            rule.snapshot()
            rule.enabled = False
            rule._changelog_message = f'Disabled: the last of its {label} ("{instance}") was deleted'[:200]
            rule.save()
            logger.warning('Naming rule "%s" disabled: the last of its %s (%s) was deleted.', rule, label, instance)


#: Model of each condition's values -> the rule fields that list it.
_CONDITION_MODELS = {}


def connect():
    """Hook the save signals of every kind's model (called from the app's ready())."""
    for kind in KINDS.values():
        model = kind.model
        uid = f'netbox_naming_convention.{kind.key}'
        post_clean.connect(name_on_clean, sender=model, dispatch_uid=f'{uid}.clean')
        pre_save.connect(name_on_save, sender=model, dispatch_uid=f'{uid}.pre_save')
        post_save.connect(record_on_save, sender=model, dispatch_uid=f'{uid}.post_save')
        pre_delete.connect(release_on_delete, sender=model, dispatch_uid=f'{uid}.pre_delete')
        post_delete.connect(forget_on_delete, sender=model, dispatch_uid=f'{uid}.post_delete')
    # Rules are kept for the rest of a request (matching.kind_rules()): a
    # changed rule must apply to the next object saved in that request.
    uid = 'netbox_naming_convention.rule'
    post_save.connect(forget_rules, sender=NamingRule, dispatch_uid=f'{uid}.post_save')
    post_delete.connect(forget_rules, sender=NamingRule, dispatch_uid=f'{uid}.post_delete')
    for name in NamingRule.CONDITION_FIELDS:
        through = getattr(NamingRule, name).through
        m2m_changed.connect(forget_rules, sender=through, dispatch_uid=f'{uid}.{name}')
        model = NamingRule._meta.get_field(name).related_model
        _CONDITION_MODELS.setdefault(model, []).append(name)
    for model in _CONDITION_MODELS:
        uid = f'netbox_naming_convention.condition.{model._meta.label_lower}'
        pre_delete.connect(note_listing_rules, sender=model, dispatch_uid=f'{uid}.pre_delete')
        post_delete.connect(disable_emptied_rules, sender=model, dispatch_uid=f'{uid}.post_delete')


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
