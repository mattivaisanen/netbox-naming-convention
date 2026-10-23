# netbox-naming-convention

A NetBox plugin that names devices from rules. A rule says which devices it
is for (a role or a device type, plus any of site, region, location, tags,
tenant, platform, status) and how their names are built, for example
`FI{site.name|first:2|upper}{role.parent.name|first:3|upper}{n}_{rack.name}`.
That rule gives an access switch in rack JK8 in Tampere the name
`FITASWI154_JK8`, where 154 is the next free number of the series
`FITASWI`.

## What it does

- **Fills in names.** A new device saved without a name gets the name of
  its rule: in the web UI, through the REST API and in CSV imports.
- **Shows the name on the device form.** When you add a device, the name
  field is grayed out and fills in as soon as the rule has what it needs
  (site, role, rack...). A small pencil button next to it unlocks the field
  so you can type your own name; pressing it again brings the rule's name
  back. The number is confirmed when you save: if someone took it in the
  meantime, the device gets the next free one.
- **Never renames on its own.** When you edit a device and change what its
  name is built from (moving it to another rack, for example), a *Suggest
  again* button appears under the name. The device keeps its number if it
  stays in the same series. Nothing changes until you press it and save, and
  with netbox-change-approval installed the rename waits for approval like
  any other edit. The only exception is a device without a name: it is
  named as soon as its rule has what it needs (for example when it gets the
  primary IP its number comes from).
- **Running numbers per series.** Each rule sets the digits (001 or 0001),
  the first and last number, numbers that are never handed out, and whether
  numbers of deleted devices are reused (gap filling). Without gap filling a
  deleted device's number never comes back.
- **Numbers from the IP**, instead of running numbers: a mask such as
  `*.*.*.N` takes the last octet of the device's primary IP, so the device
  with 192.168.10.6 is `fitaswi006`. The plugin never picks or changes IP
  addresses.
- **Existing names count.** Devices named before the rule existed are read
  (without regard to case), so the next number is right from day one.
- **Enforcement per rule:** off (only suggest and fill in), warn (names that
  don't fit are flagged on the device and listed on the rule), or refuse (a
  new device or a rename must follow the rule, and may not reuse a number).
- **Rule pages** show each series with its highest number and the next name,
  and the devices that don't follow the rule with the name they would get.

## Requirements

- NetBox **4.7** (tested with 4.7.0 and 4.7.3). NetBox refuses to load the
  plugin on older versions.
- No other plugins. Works with
  [netbox-change-approval](https://github.com/mattivaisanen/netbox-change-approval)
  when it is installed (tested with 0.3.3).

## Installation

The plugin isn't on PyPI; install it from GitHub into NetBox's own Python
environment (on a standard install, `source /opt/netbox/venv/bin/activate`
first):

```bash
pip install git+https://github.com/mattivaisanen/netbox-naming-convention.git
```

Add it to `configuration.py`:

```python
PLUGINS = [
    'netbox_naming_convention',
]
```

Then, from your NetBox install:

```bash
python manage.py migrate netbox_naming_convention
```

and restart NetBox. Settings are in [docs/configuration.md](docs/configuration.md).

With netbox-docker, add the plugin to `plugin_requirements.txt` (or
install it from a local checkout in your plugin image) and run the
migration in the netbox container.

## Upgrading

```bash
pip install --upgrade git+https://github.com/mattivaisanen/netbox-naming-convention.git
python manage.py migrate netbox_naming_convention
```

and restart NetBox.

## Rules

Under **Naming → Naming rules**. Rules are checked by priority (lowest
first); the first enabled rule that matches a device names it.

| Field | Meaning |
| --- | --- |
| Roles, device types | What kind of device the rule is for. At least one is required. Child roles match too: a rule for *Switch* covers *Switch / Access*. |
| Regions, site groups, sites, locations, tenants, platforms, statuses | Optional. Within one field any listed value matches; all fields that have values must match. Child regions and locations match too. |
| Device tags, tag match | Optional. The device needs all (or any) of the tags. Useful for categories such as `ot`. |
| Advanced condition | Optional. A filter in NetBox's permission-constraint format, such as `{"serial__startswith": "FOC"}`, or a list of filters of which any may match. |
| Template | How the name is built, see below. |
| Number source | *Running number* or *From primary IP*. |
| Digits | Numbers are padded with zeros to this many digits. |
| First number, last number | The range numbers are taken from. The last number defaults to the largest the digits allow (999 for 3). |
| Numbers never handed out | For example `0, 100-199`. |
| Fill gaps | On: the lowest free number, including those of deleted devices. Off: one more than the highest number ever handed out. |
| Number scope | *Shared*: the number counts per text before it, so racks share one run (`FITASWI154_JK8`, `FITASWI155_JK9`). *Whole name*: each full name counts on its own (`FITASWI001_JK8`, `FITASWI001_JK9`). |
| IP pattern | For *From primary IP*: a mask such as `*.*.*.N` (the octet marked N is the number) or a regular expression with one group, such as `\.([0-9]+)$`. |
| Enforcement | *Off*, *Warn* (default) or *Refuse*, see above. |

### Templates

Literal text, the number and values of the device in braces:

| Part | Gives |
| --- | --- |
| `FITASWI` | the text as written |
| `{n}` | the number, padded to the rule's digits (at most one per template) |
| `{site.name}`, `{site.slug}`, `{site.facility}` | values of the device's site |
| `{location.name}`, `{rack.name}`, `{tenant.slug}`, `{platform.name}` | values of other objects the device is in or has |
| `{role.name}`, `{role.parent.name}` | the role, or its parent (Switch for Switch / Access) |
| `{device_type.model}`, `{manufacturer.name}` | the hardware |
| `{region.name}`, `{site_group.slug}` | the site's region or group (`parent` works here too) |
| `{site.cf.code}`, `{cf.code}` | a custom field of the site, or of the device itself |
| `{device.serial}`, `{device.asset_tag}` | the device's own values |
| `{{`, `}}` | literal braces |

Filters change a value, from left to right: `{site.name|first:2|upper}`.

| Filter | Does |
| --- | --- |
| `upper`, `lower` | changes case |
| `first:N`, `last:N` | keeps the first or last N characters |
| `ascii` | removes accents (Hämeenlinna → Hameenlinna) |
| `alnum` | keeps only letters and digits |
| `nospace` | removes spaces |
| `replace:old:new` | replaces text (`replace: :-`; leave `new` out to remove) |
| `default:X` | X when the value is empty |
| `before:X`, `after:X` | adds X before or after the value, only when there is one (`{rack.name\|before:_}`) |
| `optional` | leaves the part out when it is empty |

A value that is empty and not `optional` (or `default`) makes the name wait:
the device form says "Filled in once these are set: rack". A device saved
without that value is saved without a name, unless the rule refuses names
that don't fit.

### Examples

| Devices | Template | Names |
| --- | --- | --- |
| Access switches in Tampere | `FI{site.name\|first:2\|upper}{role.parent.name\|first:3\|upper}{n}_{rack.name}` | `FITASWI154_JK8` |
| The same, rack optional | `FITASWI{n}{rack.name\|before:_\|optional}` | `FITASWI155`, `FITASWI156_JK9` |
| OT routers (tag `ot`, priority 10) | `FITAROT{n}` | `FITAROT001` |
| Printers, 4 digits | `{site.slug\|upper}-PRN{n}` | `TAMPERE-PRN0001` |
| Switches numbered by IP | `fitaswi{n}`, mask `*.*.*.N` | `fitaswi006` for 192.168.10.6 |

## REST API

- `/api/plugins/naming-convention/rules/`: the rules (create, read, update,
  delete), like any NetBox object.
- `POST /api/plugins/naming-convention/suggest/`: send a device's values
  (`site`, `role`, `rack`, `device_type`, `tags` as ids, ...; or `device`
  for an existing one) and get the rule, the name, the number and the values
  it still waits for. Saves and reserves nothing. Needs permission to add or
  change devices.
- `POST /api/dcim/devices/` without a `name` gets the rule's name, as in
  the web UI.

## With netbox-change-approval

Naming rules are ordinary NetBox objects, so changes to them need approval
like changes to any other object. A new device is written at once by
change-approval (marked pending), so it gets its name and number right
away; a rename waits for approval. The plugin's own record of the numbers
handed out is never gated.

## License

Apache 2.0, see [LICENSE](LICENSE).
