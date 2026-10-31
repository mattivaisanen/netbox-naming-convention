# Developer guide

How the plugin works and why, for anyone changing it. "Device" below
stands for any object a rule can name (device, virtual machine, rack) unless
it says otherwise.

## Kinds of objects

`kinds.py` holds everything that differs between devices, virtual machines
and racks, one `Kind` each: the rule's condition fields and where each is
read on the object (`Condition.path`, `tree` for nested objects), which
conditions a rule needs (devices: role or device type), the template roots
and the object's own values, the *Wait for* choices and default, the status
choices, whether the number can come from a primary IP, whether NetBox
requires a name, the longest name, and the url names of the forms and the
CSV import. `NamingRule.object_type` picks one (`rule.kind`). The rest of
the plugin asks the kind instead of naming devices: `rules_queryset(kind)`,
`find_rule()` (only rules of the object's kind), `rule_matches()` (walks
`kind.conditions`), `rule_objects()`, `Template(text, kind)`,
`used_numbers(..., model)`, `series_key(..., kind)`. Supporting another kind
means a `Kind` here, its condition fields on `NamingRule` (and the form,
serializer and migration) and its values in `reference.VALUES`.

`Kind.defaults` fills in what NetBox only fills in on save, so a rule sees
an object on its form as it will be saved: a virtual machine without a site
gets its cluster's (or host device's) site, as `VirtualMachine.save()`
does. `kinds.prepare(obj)` runs it at the start of `find_rule()` and
`naming.render_name()`, and changes only empty fields.

On the add forms the name stays locked while nothing a rule could match on
is chosen yet (`kindsSet()` in `name_form.html`): a device needs role and
device type, other kinds any of their form fields besides status. Without
that, the lock would drop the moment the empty form found no rule.

## Modules

| Module | Does |
| --- | --- |
| `kinds.py` | Devices, virtual machines and racks: what differs between them (see above). |
| `template.py` | Parses a template into text, value and number parts; renders it for an object; lists missing values. Unknown values and filters are refused when a rule is saved. No database. |
| `numbering.py` | Series keys, the regular expression that reads a number back out of a name, used numbers (from names in the database), the next number, numbers from an IP. |
| `matching.py` | Which rule names an object (in memory, see below), and `rule_objects()` for the rule page and the preview. |
| `naming.py` | `suggest()` (no writes), `assign()` and `reserve()` (under the series lock), `remember()`, `follows()`, `check_typed_name()`. |
| `signals.py` | The save hooks, connected for each kind's model by `signals.connect()` in `ready()`. |
| `api/patches.py` | The wrapped NetBox serializers (see below). |
| `template_content.py`, `templates/.../inc/name_form.html` | The naming panel, the name field script on the add and edit forms, and the note on netbox-change-approval's change request page. |
| `reference.py`, `views.TemplateReferenceView` | The template reference page linked from the rule form. Tests check it lists every value root and filter of `template.py`. |
| `forms.py` | The rule form. `object_type` and `number_source` are `HTMXSelect`s: changing them draws the form again with only the conditions, *Wait for* values and number fields that apply (like NetBox's rack form does for rack types). |
| `report.py`, `views.NamingReportView` | The naming report (see below). |
| `preview.py`, `views.NamingRulePreviewView` | The preview on the rule form (see below). |
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
the common lookups, like change-approval's `matching.py`. Each step must be
a model field (`_meta.get_field()`, so no private attributes or methods),
and private data is never followed (`matching._PRIVATE_APPS` and
`_PRIVATE_MODELS`: users, tokens and permissions, data sources and the
change log, content types, webhooks and event rules): which rule matches
shows on every device form and in the rule preview, so a condition could
otherwise read a password hash or a data source's credentials.
`constraint_errors()` refuses such keys and unknown fields when a rule is
saved.

## Waiting for values

`NamingRule.required_values` lists fields (`RequiredValueChoices`, limited
to `Kind.wait_for`) the rule needs besides its template's values. `naming.render_name()` puts the
empty ones first in `missing`, so they behave exactly like an empty template
value: the form waits, a save leaves the device unnamed (or is refused with
enforcement *refuse*; for virtual machines and racks, which must have a
name, it is a validation error). The default is `default_required_values()`:
site, role and device type, what NetBox's device form requires. A new rule
of another kind left at that default gets its kind's default on save
(`NamingRule._default_wait_for()`). The form script
shows missing keys by the form's own labels (TomSelect moves a select's
label to `id_<field>-ts-control`).

## Filters for the whole name

`NamingRule.name_filters` (`template.parse_name_filters()`, limited to
`NAME_FILTERS`) is applied by `naming.render_name()` to the rendered prefix and
suffix separately, so the number is never touched and series, used numbers
and `follows()` all see the filtered text. `filter_name()` leaves the
number marker and `<missing>` placeholders of `Rendered.pattern` alone.

## Series and numbers

The series of a name is its prefix (the rendered text before `{n}`) for
scope *shared*, or `prefix#suffix` for *whole name*, lowercased, after the
kind (`device:ams1-sw`), so devices and racks named alike count apart. Used
numbers are read from the names of the kind's model with one `name__iregex` query, so names
given by hand and names from before the rule count. `NamingSeries` keeps the
highest number ever handed out per series; without gap filling the next
number is one more than the higher of that and the highest used number, so a
deleted device's number never comes back. With gap filling the lowest free
number from `number_first` wins and the high-water mark is ignored. Used
numbers above the rule's last number don't count, and `next_number()` jumps
over skipped ranges instead of stepping through them.

A letter counter (`{a-z}`, `{A-Z}`) is the same whole number underneath, 1
to 26. Only the edges change: `rule.format_number()` writes it as a letter,
`numbering.name_regex(..., letters=True)` matches one letter, and
`read_number()` turns it back into a number. Series, high-water marks and
gap filling don't know the difference.

`NamingSeries` is a plain model on purpose: approval plugins gate every
NetBoxModel, and taking a number must never wait for approval. The same
goes for `AssignedName` (below), which points at any object through a
generic foreign key and is deleted with it (post_delete).

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
   here instead of trusting the one from validation. If no number is free
   any more (the series filled up meanwhile), pre_save raises
   `AbortRequest`, which NetBox's views, import and API show as an ordinary
   error, rather than save the number from validation twice. A device saved
   without a name (often without validating) just stays unnamed. A name
   given by hand is only remembered (`remember()` raises the high-water
   mark, for numbers within the rule's range).
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

## The name field

`NameFormHelper.head()` (a `PluginTemplateExtension` for all pages,
because `head()` is the only hook on edit pages) adds
`inc/name_form.html` on the add and edit pages of each kind
(`Kind.add_view`, `Kind.edit_view`). The script sends `object_type` and the
form's values (`Kind.form_fields`) to the suggest endpoint whenever they change
(form `change` events, plus a check every 1.5 s because TomSelect does not
always produce one), with the session cookie and CSRF token. A field on
the form that is empty is sent as `null`, so the edit form's suggestion
does not fall back to the device's saved value.

Some NetBox forms redraw their fields through HTMX when a select changes
(the virtual machine form's *Type*). The redraw puts in a new `id_name`
input, so the script builds its buttons and note again on
`htmx:afterSettle` (`attach()`), keeping its state.

- Add: the field starts locked (read-only and grayed)
  before anything is chosen, so nobody types a name the rule would have
  given; it says it is filled in once the fields every rule of that kind
  needs (`Kind.kind_fields`; for devices site, role and device type, what
  NetBox needs to save one) are set, or for kinds without such fields once
  anything is chosen. When they are set and no rule matches, the field is
  NetBox's own again; when one is cleared again, the field goes back to
  waiting (unless the person unlocked it). While
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

## The rule form preview

The *Try on* field uses `forms.PreviewObjectSelect`, NetBox's
`APISelect` with the preview below it
(`templates/.../inc/preview_object.html`); its queryset follows the object
type. The preview `hx-post`s the whole
rule form to `NamingRulePreviewView` on load and whenever the form changes
(`?rule=<pk>` when editing), so it is drawn again when the number source
redraws the form too. The field is not a model field and is never saved.

The view validates a `NamingRuleForm` without saving, and
`preview.rule_draft()` turns `form.instance` into the rule as the form has
it: enabled, and its conditions put in Django's prefetch cache
(`instance._prefetched_objects_cache`, one evaluated queryset per field of
`CONDITION_FIELDS`), so `rule.roles.all()` and `.exists()` answer from the
form. Django reads many-to-many values only from an instance with a primary
key, so a new rule gets `pk = 0` (`UNSAVED_PK`). `matching.rule_objects()`
puts the rule it is given in place of its saved version when it orders the
rules, which is what lets the draft be compared with the other rules.
Devices are those the user may view; numbers are kept distinct within the
preview like on the rename page.

## The naming report

`report.build_report()` goes through the objects of one kind the user may
view (at most `REPORT_LIMIT`), finds each one's rule with the rules loaded
once (`find_rule(obj, rules, tag_slugs)`, tags prefetched) and puts it in a
group: `drifted`, `unnamed`, `no_rule` or `follows`. Only the objects of
the group shown get a suggestion (at most `REPORT_SHOWN`, numbers kept
distinct like on the rename page).

## Renaming from the rule page or the report

`NamingRuleRenameView` (one rule) and `NamingReportRenameView` (each object
by its own rule) take the ticked objects, work out their new names
with `rename_plan()` (`suggest(..., taken=...)` keeps numbers distinct
within the batch) and shows old and new names. The confirm button posts
`id,name` CSV to NetBox's own import for the kind (`Kind.import_view`), with
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

## Reserved names

`naming.reserve()` takes numbers like `assign()`: under the series lock,
raising the high-water mark. The rows are `ReservedName`, a plain model
like `NamingSeries` (reserving must not wait for approval), with a
`RestrictedQuerySet` manager so NetBox's object permissions and
`BaseViewSet` work on it. `_pick()` adds the numbers of the series' active
reservations to the used ones, except a reservation of the object's own
name, so the object a name was reserved for can take it (also under
*Refuse*, where `check_typed_name()` says a number is reserved). post_save
deletes a reservation of the saved object's name. Expired reservations are
ignored when numbers are picked and deleted when their series reserves
again. Reserving ignores the rule's *Wait for* fields (`_render(waits=False)`):
the objects don't exist yet, only the template's values count.

## REST API: the wrapped serializers

NetBox's `ValidatedModelSerializer.validate()` runs `full_clean()` on a
*copy* of the object and later creates the real one from the request data,
so the name post_clean puts on the copy is lost. `api/patches.py` wraps
`validate` of `DeviceSerializer`, `VirtualMachineSerializer` and
`RackSerializer` (their config-context subclasses inherit it): before
NetBox's validation, a new object sent without a name gets the rule's name
in the data (so NetBox's own checks see it), and the name is marked as
the plugin's for this request (a set on the request, since the saved
instance is a different object), so pre_save picks the number again under
the lock. NetBox 4.7.3 has `Meta.model_clean_fields` for this, but 4.7.0
doesn't. Virtual machines and racks must have a name, so DRF makes it a
required field; `get_fields` of those two serializers is wrapped to make it
optional on create. Without a rule NetBox's model validation still refuses
the missing name.

Model validation (`full_clean()`) checks a required name before post_clean
runs, so for virtual machines and racks names are filled in by the form
script (which posts the rule's name with `_naming_auto=1`), the API wrapper
and pre_save (a plain `save()`), not by validation alone. CSV import of
virtual machines and racks needs a name for the same reason.

## Tests

`tests/test_template.py` (no database), `tests/test_naming.py` (numbers,
series, enforcement, editing, number from IP, two saves at once),
`tests/test_api.py`, `tests/test_views.py` (rule pages, device form, CSV
import, device panel) and `tests/test_change_approval.py` (skipped unless
installed). With change-approval installed the other tests write as an
approved change would (`NetBoxData.gated = False`), so its gate stays out of
their way.
