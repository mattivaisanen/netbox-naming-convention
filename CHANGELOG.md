# Changelog

## Unreleased

New:

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
- On the device form, clearing a field the name waits for (such as the
  site) after a rule had filled in the name left the name field open to
  typing, or kept the old suggestion on the edit form. The name is now
  taken away and the field waits again until the field is set.

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
