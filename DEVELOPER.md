# Developer guide

How the plugin works and why, for anyone changing it.

## Modules

| Module | Does |
| --- | --- |
| `template.py` | Parses a template into text, value and number parts; renders it for a device; lists missing values. Unknown values and filters are refused when a rule is saved. No database. |
| `numbering.py` | Series keys, the regular expression that reads a number back out of a name, used numbers (from device names in the database), the next number, numbers from an IP. |
| `matching.py` | Which rule names a device (in memory, see below), and `rule_devices()` for the rule page. |
| `naming.py` | `suggest()` (no writes), `assign()` (under the series lock), `remember()`, `follows()`, `check_typed_name()`. |
| `signals.py` | The device save hooks. |
| `api/patches.py` | The one wrapped NetBox internal (see below). |
| `template_content.py`, `templates/.../inc/device_form.html` | The device panel and the device form script. |
| `integrations.py` | Detects netbox-change-approval (no code depends on it). |

## Matching a device that has no row yet

A device being created has no primary key, so rules are matched on the
instance: foreign keys are read from it, tags from `instance._m2m_values`
(NetBox's model forms and API serializers put the many-to-many values there
before validation), or from the database for a saved device without them.
Roles, regions, locations and site groups match their ancestors by walking
`parent` in Python, so it does not depend on how NetBox stores the
trees. The advanced condition is evaluated in memory with
the common lookups, like change-approval's `matching.py`.

## Series and numbers

The series of a name is its prefix (the rendered text before `{n}`) for
scope *shared*, or `prefix#suffix` for *whole name*, lowercased. Used
numbers are read from device names with one `name__iregex` query, so names
given by hand and names from before the rule count. `NamingSeries` keeps the
highest number ever handed out per series; without gap filling the next
number is one more than the higher of that and the highest used number, so a
deleted device's number never comes back. With gap filling the lowest free
number from `number_first` wins and the high-water mark is ignored.

`NamingSeries` is a plain model on purpose: approval plugins gate every
NetBoxModel, and taking a number must never wait for approval.

## Saving a device

1. **post_clean** (NetBox sends it from `CustomValidationMixin.clean()`, so
   for forms, CSV import and API validation): for a device without a name,
   `suggest()` fills it in (so NetBox's own uniqueness check sees it) and
   marks it as the plugin's (`naming.mark_auto()`). A full series is a
   validation error. A name typed by hand is checked by `check_typed_name()`
   when the rule refuses names that don't fit, but only on create or when
   the name changes, so editing anything else of a legacy device still works.
2. **pre_save**: a name marked as the plugin's (or still empty) is picked
   again by `assign()`: `NamingSeries` row created if needed
   (`bulk_create(ignore_conflicts=True)`), locked with
   `select_for_update()`, used numbers read again, the number taken and the
   high-water mark raised. NetBox's views, API and CSV import save inside a
   transaction, so the lock is held until the device is committed and a
   second device saved at the same moment waits and then sees the first
   (`tests/test_naming.py` `ConcurrencyTests`). Validation runs *outside*
   that transaction in the views, which is why the number is picked again
   here instead of trusting the one from validation. A name given by hand is
   only remembered (`remember()` raises the high-water mark).
3. pre_save also covers code that saves without validating: NetBox's IP
   form sets a device's primary IP with a plain `save()`, so a rule that
   numbers by IP names the device right then.

A device that has a name is never renamed by these hooks.

## The device form

`DeviceFormHelper.head()` (a `PluginTemplateExtension` for all pages,
because `head()` is the only hook on edit pages) adds
`inc/device_form.html` on `dcim:device_add` and `dcim:device_edit`. The
script sends the form's values to the suggest endpoint whenever they change
(form `change` events, plus a check every 1.5 s because TomSelect does not
always produce one), with the session cookie and CSRF token.

- Add: while locked, the name field is read-only and holds the rule's name,
  and a hidden `_naming_auto=1` goes with the form. `signals._form_says_auto()`
  sees it and treats the name as the plugin's, so the number is picked again
  under the lock at save. The pencil button unlocks the field and removes the
  marker; what is in the field is then a typed name.
- Edit: never changes the field on its own. When the suggestion differs from
  the name, a *Suggest again* button puts it in the field.

The setting `device_form` turns the script off.

## REST API: the wrapped serializer

NetBox's `ValidatedModelSerializer.validate()` runs `full_clean()` on a
*copy* of the device and later creates the real one from the request data,
so the name post_clean puts on the copy is lost. `api/patches.py` wraps
`DeviceSerializer.validate`: after NetBox's validation, a new device sent
without a name gets the rule's name in the data, and the name is marked as
the plugin's for this request (a set on the request, since the saved
instance is a different object), so pre_save picks the number again under
the lock. NetBox 4.7.3 has `Meta.model_clean_fields` for this, but 4.7.0
doesn't.

## Tests

`tests/test_template.py` (no database), `tests/test_naming.py` (numbers,
series, enforcement, editing, number from IP, two saves at once),
`tests/test_api.py`, `tests/test_views.py` (rule pages, device form, CSV
import, device panel) and `tests/test_change_approval.py` (skipped unless
installed). With change-approval installed the other tests write as an
approved change would (`NetBoxData.gated = False`), so its gate stays out of
their way.
