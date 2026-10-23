# Changelog

## Unreleased

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
