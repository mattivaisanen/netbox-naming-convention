# Working on this repo

NetBox plugin that names devices from rules (template + running number per
series). Follows the conventions of mattivaisanen/netbox-change-approval,
netbox-fortigate-importer and netbox-local-dateformat.

## Rules

- **Never rename on its own.** Only a device without a name is named by the
  plugin; a rename is always a person's edit (*Suggest again*), so approval
  plugins see it as one.
- **No IP selection.** IP suggestion is a separate plugin. This plugin may
  only read a number from a device's primary IP.
- **Numbers are taken under the series lock** (`naming.assign()`), inside
  the save's transaction. Never trust a number chosen during validation.
- **Bookkeeping models are not NetBoxModel** (`NamingSeries`): approval
  plugins gate every NetBoxModel, and taking a number must not need approval.
  Naming rules are NetBoxModels on purpose: their changes are gated.
- **No hard dependencies on other plugins.** netbox-change-approval is
  detected with `integrations.has_change_approval()` and imported only inside
  functions. CI tests with and without it.
- **Matti's NetBox:** Matti restarts it themselves (netbox-docker in
  ~/netbox-docker). After pushing, pull into
  ~/projects/netbox-naming-convention on their machine and tell them it's
  ready to restart. Keep test runs minimal (token cost).
- **NetBox support:** only claim what CI tests. `min_version` is the oldest
  release in the CI matrix; keep README "Requirements" in sync. Migrations
  depend only on migrations that exist in that oldest release.
- **Python:** `requires-python >= 3.10`; CI runs 3.12.
- **Packaging:** setuptools via `pyproject.toml`, no runtime dependencies.
  Keep `version` in `pyproject.toml` and `NamingConventionConfig.version` the
  same. Non-`.py` files must be listed in package-data.
- **Tests:** Django tests in `netbox_naming_convention/tests/`, run with
  `python manage.py test netbox_naming_convention` from a NetBox checkout.
  Every behaviour change gets a test. Never skip or weaken a test to get CI
  green. Tests that need change-approval use `skipUnless(installed)`.
- **Docs:** update in the same commit as the change: README.md,
  DEVELOPER.md (every wrapped NetBox internal), docs/configuration.md (every
  setting), CHANGELOG.md (`## Unreleased` on top, `New:` / `Fixed:` lists
  written for NetBox users).
- **Commits:** subject says what changes for the user, in plain words. Body
  explains the problem, then the fix, in plain language.
