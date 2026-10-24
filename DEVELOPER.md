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
| `template_content.py`, `templates/.../inc/device_form.html` | The device panel, the device form script, and the note on netbox-change-approval's change request page. |
| `reference.py`, `views.TemplateReferenceView` | The template reference page linked from the rule form. Tests check it lists every value root and filter of `template.py`. |
| `forms.py` | The rule form. `number_source` is an `HTMXSelect`: changing it draws the form again without the fields of the other source (like NetBox's rack form does for rack types). |
| `integrations.py` | Detects netbox-change-approval (no code depends on it). |

## Which rule wins

`matching.ordered_rules()`: priority (lowest first), then
`NamingRule.specificity` (how many kinds of conditions are set: each
many-to-many field, statuses and the advanced condition count one each),
most first, then name. Sorted in Python because specificity counts
prefetched relations. Every caller of `find_rule()` and the rule page use
this order.

## Matching a device that has no row yet

A device being created has no primary key, so rules are matched on the
instance: foreign keys are read from it, tags from `instance._m2m_values`
(NetBox's model forms and API serializers put the many-to-many values there
before validation), or from the database for a saved device without them.
Roles, regions, locations and site groups match their ancestors by walking
`parent` in Python, so it does not depend on how NetBox stores the
trees. The advanced condition is evaluated in memory with
the common lookups, like change-approval's `matching.py`.

## Waiting for values

`NamingRule.required_values` lists device fields (`RequiredValueChoices`)
the rule needs besides its template's values. `naming._render()` puts the
empty ones first in `missing`, so they behave exactly like an empty template
value: the form waits, a save leaves the device unnamed (or is refused with
enforcement *refuse*). The default is `default_required_values()`: site,
role and device type, what NetBox's device form requires. The form script
shows missing keys by the form's own labels (TomSelect moves a select's
label to `id_<field>-ts-control`).

## Filters for the whole name

`NamingRule.name_filters` (`template.parse_name_filters()`, limited to
`NAME_FILTERS`) is applied by `naming._render()` to the rendered prefix and
suffix separately, so the number is never touched and series, used numbers
and `follows()` all see the filtered text. `filter_name()` leaves the
number marker and `<missing>` placeholders of `Rendered.pattern` alone.

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
NetBoxModel, and taking a number must never wait for approval. The same
goes for `AssignedName` (below).

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
4. When pre_save named the device, it adds "Name from naming rule ..." to
   `instance._changelog_message` (after a message the user typed, within
   NetBox's 200 characters), which NetBox's `to_objectchange()` writes into
   the change log entry. **post_save** then records the name in
   `AssignedName` (device, name, rule, how).
5. Edit form: when the posted name equals `_naming_suggested` (put there by
   *Suggest again*) and still equals the rule's suggestion, post_clean
   records it as `suggested` in `AssignedName`, and pre_save adds "Name
   suggested by naming rule ..." to the change log message (the view sets
   the message only after validation).

`AssignedName` is what the device panel ("Given by") reads. The note on
netbox-change-approval's change request page is a
`PluginTemplateExtension.alerts()` for the model label
`netbox_change_approval.changerequest`: just a string, so nothing is
imported from that plugin, and it only ever matches when it is installed.
`requested_device()` builds the device as the request would leave it (a
pending create is already saved; for an update the `diff`'s new values are
set on an in-memory copy). The note then says the name was filled in by the
rule (from `AssignedName`), follows the rule, or doesn't (with the rule's
suggestion, from the device's current name). A rename that waits for
approval is not in `AssignedName` (change-approval undoes the edit's
writes when it queues it), which is why the note checks the rule instead.

## The device form

`DeviceFormHelper.head()` (a `PluginTemplateExtension` for all pages,
because `head()` is the only hook on edit pages) adds
`inc/device_form.html` on `dcim:device_add` and `dcim:device_edit`. The
script sends the form's values to the suggest endpoint whenever they change
(form `change` events, plus a check every 1.5 s because TomSelect does not
always produce one), with the session cookie and CSRF token. A field on
the form that is empty is sent as `null`, so the edit form's suggestion
does not fall back to the device's saved value.

- Add: the field starts locked (read-only, grayed, a padlock in front)
  before anything is chosen, so nobody types a name the rule would have
  given; it says it is filled in once site, role and device type are set
  (`BASICS`, what NetBox needs to save a device). When they are set and no
  rule matches, the field is NetBox's own again; when one is cleared again,
  the field goes back to waiting (unless the person unlocked it). While
  locked, the field holds the rule's name and a hidden `_naming_auto=1` goes
  with the form. `signals._form_says_auto()` sees it and treats the name as
  the plugin's, so the number is picked again under the lock at save. The
  pencil button unlocks the field and removes the marker; what is in the
  field is then a typed name.
- Edit: never changes the field on its own. `head()` checks `follows()`:
  a name that follows its rule starts locked like on add (the pencil unlocks
  it). When the suggestion differs from the name, a *Suggest again* button
  puts it in the field and adds `_naming_suggested=<name>` (see "Saving a
  device", step 5).

The script is left out when there are no enabled rules. The setting
`device_form` turns it off.

The lock is a convenience, not protection: anyone can unlock it, and the
API and CSV import have no form. A rule with enforcement *refuse* is what
makes the server turn down names that don't follow it.

## Renaming from the rule page

`NamingRuleRenameView` takes the ticked devices, works out their new names
with `rename_plan()` (`suggest(..., taken=...)` keeps numbers distinct
within the batch) and shows old and new names. The confirm button posts
`id,name` CSV to NetBox's own `dcim:device_bulk_import`, with
`_naming_rename=1` so post_clean records the names as suggested. Using
NetBox's import instead of saving here means its permission checks, change
log and netbox-change-approval's bulk handling apply unchanged.

## Suggestions on edit

`suggest()` on a saved device keeps the number of its current name when the
name is in the series; otherwise it tries the names `AssignedName` has for
the device (newest first), so a device renamed by hand gets its own number
back while no other device has it. The form sends the device's stored name,
not what is typed in the field, so typing doesn't change the suggestion.
`Suggestion.pattern` (from `Rendered.pattern`) is the rule's name for the
device with `###` for the number and `<rack>` for a missing value, for the
form's hint.

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
