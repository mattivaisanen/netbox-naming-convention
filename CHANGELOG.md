# Changelog

## Unreleased

New:

- Naming report (*Naming → Naming report*): every device, virtual machine
  or rack whose name doesn't follow its rule, that has no name yet, or that
  no rule names, with the suggested names and *Rename selected*.
- Rules can name virtual machines and racks too. A rule's *Names* field
  says which; the form then shows that kind's conditions (clusters,
  virtual machine types, rack roles, rack types...), *Wait for* values and
  template values (`{cluster.name}`, `{rack.facility_id}`...). Virtual
  machine and rack forms get the same locked name field, the naming panel
  and *Suggest again*, the REST API fills in their names, and the rule page
  renames them in bulk. Devices, virtual machines and racks count their
  numbers separately. Existing rules keep naming devices. A virtual
  machine with only a cluster is matched and named with the cluster's site,
  the site NetBox gives it when it is saved.
- The rule form previews the rule as you type: what names look like, the
  names it would give the first ten of its devices, and the name a device
  you pick would get (and whether another rule names it first). Nothing is
  saved.
- *Wait for* per rule: the fields that must be set before the name is
  filled in. New rules wait for site, device role and device type.
- The hint under the device name is on separate lines: the rule, what
  names look like with the missing parts marked (`[Rack]`), and what it
  still waits for, by the form's own field names.
- Filters for the whole name per rule, such as `ascii|nospace|lower`, so
  you don't have to repeat them on every value of the template.
- The rule form links to a reference page in NetBox with every value and
  filter a template can use.
- The rule form shows only the number fields that apply: first and last
  number, numbers never handed out and gap filling for running numbers, the
  IP pattern for numbers from the IP.
- The device add form keeps the name locked from the start, until the role
  and device type show whether a rule names the device. The edit form grays
  out a name that follows its rule too; the pencil button unlocks it.
- The device's change log entry says when its name came from a rule, the
  device page shows whether the rule filled the name in or suggested it, and
  with netbox-change-approval the change request page says whether the
  name was filled in by the rule, follows it, or doesn't.
- Devices that don't follow their rule can be renamed in bulk from the
  rule page: tick them, check old and new names, confirm. The renames go
  through NetBox's device import (change log, approvals).
- The name hint on the device form says what the convention is, such as
  "Naming convention for "Switches" is AMS1-SW###-R02, suggested name:
  AMS1-SW014-R02", instead of only the rule's name.

Fixed:

- *Rename selected to the suggested names* on a rule page had no
  checkboxes to select with.
- With two rules on the same priority, the one first by name won, even
  when the other matched more (a switch tagged OT got the general switch
  rule). Now the rule with more kinds of conditions wins on a tie.
- The grayed-out name field was hard to tell from a normal one. It is now
  clearly gray, with a padlock.
- Examples in the documentation and help texts are generic.
- On the edit form, typing in the name field changed the suggestion to the
  next free number. The suggestion now comes from the name the device has.
- A device renamed by hand was offered a new number. It now gets back the
  number the rule gave it, while no other device has taken it.
- One device with a name above the rule's range, such as SW5000 in a
  3-digit series, made the series "full" for every new device. Numbers
  above the range are now ignored when picking the next one.
- A name typed by hand with a very long number (SW99999999999) made saving
  the device fail with a server error. Numbers outside the rule's range are
  no longer remembered as handed out.
- A large range in *Numbers never handed out*, such as `1-999999000`, made
  saving a device take minutes. Skipped ranges are now jumped over at once.
- When the number shown on the form was taken by someone else and the
  series had no other free number, the device was saved with the taken
  number anyway. Saving now stops with "The series ... is full".
- The advanced condition could follow a device's relations to users, so
  someone who may edit rules could test a user's password hash one
  character at a time. Conditions can't reach users, their API tokens or
  preferences any more, and the rule form refuses fields devices don't have.
- The rule page and *Rename selected* ran many database queries per device;
  they run far fewer now.

## 0.1.0 (2026-10-23)

New:

- Naming rules for devices: what kind of device (role or device type) and
  optionally site, region, location, tags, tenant, platform, status or an
  advanced condition; a template of fixed text, values cut from names and a
  number; digits, number range, numbers never handed out, gap filling and
  number scope per rule.
- Devices saved without a name get their rule's name, in the web UI, the
  REST API and CSV imports. Two devices saved at the same time never get the
  same number.
- The device add form grays out the name and fills it in from the rule,
  with a button to type your own. The edit form offers *Suggest again* and
  never renames on its own.
- Numbers can come from the device's primary IP (mask or regular
  expression).
- Enforcement per rule: off, warn, or refuse names that don't follow the
  rule.
- Rule pages with each series, its highest number and next name, and the
  devices that don't follow the rule. A naming panel on every named device.
- REST API for rules and a `suggest` endpoint.
