# netbox-naming-convention

A NetBox plugin that names devices, virtual machines and racks from rules. A
rule says which objects it is for (for devices a role or a device type, plus
any of site, region, location, tags, tenant, platform, status) and how their
names are built, for example
`{site.slug|upper}-{role.slug|first:2|upper}{n}-{rack.name}`. That rule
gives a switch in rack R01 at the site `ams1` the name `AMS1-SW014-R01`,
where 014 is the next free number of the series `AMS1-SW`.

## What it does

Everything below works the same for devices, virtual machines and racks;
"device" stands for any of them.

- **Fills in names.** A new device saved without a name gets the name of
  its rule: in the web UI, through the REST API and in CSV imports.
- **Shows the name on the device form.** When you add a device, the name
  field is grayed out and locked from the start, and fills in as soon as
  the rule has what it needs (role, device type, site, rack...). A small
  pencil button next to it unlocks the field so you can type your own name;
  pressing it again brings the rule's name back. The number is confirmed
  when you save: if someone took it in the meantime, the device gets the
  next free one. When you edit a device whose name follows its rule, the
  name is grayed out the same way.
- **Never renames on its own.** When you edit a device and change what its
  name is built from (moving it to another rack, for example), a *Suggest
  again* button appears under the name, with a hint such as "Naming
  convention for "Switches" is AMS1-SW###-R02, suggested name: AMS1-SW014-R02".
  The device keeps its number if it stays in the same series, and a device
  whose name was changed by hand gets back the number the rule gave it, as
  long as no other device has taken it. Nothing changes until you press it and save, and
  with netbox-change-approval installed the rename waits for approval like
  any other edit; the change request says whether the new name follows the
  rule. The only exception is a device without a name: it is
  named as soon as its rule has what it needs (for example when it gets the
  primary IP its number comes from).
- **Running numbers per series.** Each rule sets the digits (001 or 0001),
  the first and last number, numbers that are never handed out, and whether
  numbers of deleted devices are reused (gap filling). Without gap filling a
  deleted device's number never comes back (numbers of devices that were
  never approved in netbox-change-approval do).
- **Numbers from the IP**, instead of running numbers: a mask such as
  `*.*.*.N` takes the last octet of the device's primary IP, so with the
  template `sw{n}` the device with 10.0.0.6 is `sw006`. The plugin never
  picks or changes IP addresses.
- **Says where a name came from.** The device's change log entry says
  "Name from naming rule ..." (after any message you typed), and the device
  page shows whether the rule filled the name in or suggested it.
- **Existing names count.** Devices named before the rule existed are read
  (without regard to case), so the next number is right from day one.
- **Enforcement per rule:** off (only suggest and fill in), warn (names that
  don't fit are flagged on the device and listed on the rule), or refuse (a
  new device or a rename must follow the rule, and may not reuse a number).
- **Preview while you write a rule.** The rule form shows the names the
  rule would give its devices, and to any device you pick, as you type.
- **Rule pages** show each series with its highest number and the next name,
  and the devices that don't follow the rule with the name they would get.
  Tick some of them and *Rename selected to the suggested names* shows old
  and new names; confirming sends them through NetBox's own device import,
  so permissions, the change log and approvals work as for any bulk edit.
- **Naming report** (*Naming → Naming Report*): for devices, virtual
  machines and racks, how many have a name that doesn't follow their rule,
  have no name yet, aren't named by any rule, or follow their rule, with a
  count per rule. Each group lists its objects (the first 100) with the
  rule and the suggested name, and the same *Rename selected* as on a rule
  page, here with each object renamed by its own rule. Only objects you may
  view are counted, up to 5000 per kind.

## Requirements

- NetBox **4.7 or later** (tested with 4.7.0 and 4.7.3). NetBox refuses to
  load the plugin on older versions.
- No other plugins. Works with
  [netbox-change-approval](https://github.com/mattivaisanen/netbox-change-approval)
  when it is installed (tested with 0.4.0).

## Installation

The plugin isn't on PyPI; install it from GitHub into NetBox's own Python
environment (on a standard install, `source /opt/netbox/venv/bin/activate`
first):

```bash
pip install git+https://github.com/mattivaisanen/netbox-naming-convention.git@v0.2.0
```

Releases are listed under
[Releases](https://github.com/mattivaisanen/netbox-naming-convention/releases);
leave out `@v0.2.0` to install the latest code from `main`.

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

Under **Naming → Naming Rules**. Rules are checked by priority (lowest
first); the first enabled rule that matches a device names it. On the same
priority, the rule with more kinds of conditions is checked first, so a rule
for switches tagged `lab` wins over one for all switches; after that, by
name. Set different priorities when you want a fixed order.

| Field | Meaning |
| --- | --- |
| Names | What the rule names: devices, virtual machines or racks. The form shows the conditions, *Wait for* values and template values of that kind. |
| Roles, device types | Devices: what kind of device the rule is for. At least one is required. Child roles match too: a rule for *Switch* covers *Switch / Access*. |
| Roles, virtual machine types, clusters | Virtual machines, optional. A rule without conditions names every virtual machine. |
| Rack roles, rack types | Racks, optional. A rule without conditions names every rack. |
| Regions, site groups, sites, locations, tenants, platforms, statuses | Optional. Within one field any listed value matches; all fields that have values must match. Child regions and locations match too. |
| Device tags, tag match | Optional. The device needs all (or any) of the tags, for categories of devices that roles don't tell apart. |
| Advanced condition | Optional. A filter in NetBox's permission-constraint format, such as `{"serial__startswith": "FOC"}`, or a list of filters of which any may match. Users, tokens and permissions, data sources, the change log, content types, webhooks and event rules can't be used. |
| Template | How the name is built, see below. |
| Wait for | The fields that must be set before the name is filled in, besides the values the template uses, such as site, location, rack, role, device type, cluster, tenant, platform, serial number or asset tag (the form lists those of the rule's kind). New device rules wait for site, role and device type (what the device form requires), rack rules for the site, virtual machine rules for nothing. |
| Filters for the whole name | Optional. Filters applied to the whole name after the template, such as `ascii\|nospace\|lower`: `upper`, `lower`, `ascii`, `alnum`, `nospace`, `replace:old:new`. The number is never changed. |
| Number source | *Running number* or *From primary IP*. |
| Digits | Numbers are padded with zeros to this many digits (3 gives `007`). Numbers from the IP too; 1 leaves them as they are. Not used by a letter counter. |
| First number, last number | Running numbers only. The range numbers are taken from. The last number defaults to the largest the digits allow (999 for 3), or 26 (`z`) for a letter counter, where `a` is 1. |
| Numbers never handed out | Running numbers only. For example `0, 100-199`, or letters for a letter counter: `i, o, x-z`. |
| Fill gaps | Running numbers only. On: the lowest number no device has now, including those of deleted devices. Off: one more than the highest number ever handed out, so gaps are never refilled (a name with a free number can still be typed by hand). The plugin can't tell a gap left on purpose from one left by accident: retire numbers on purpose with *Numbers never handed out*, or keep the retired device in NetBox (its number counts as used while it exists). |
| Number scope | *Shared*: the number counts per text before it, so racks share one run (`AMS1-SW014-R01`, `AMS1-SW015-R02`). *Whole name*: each full name counts on its own (`AMS1-SW001-R01`, `AMS1-SW001-R02`). |
| Member suffix | Optional. An ending a name may have after the number, for members of a stack or cluster. `#` is one or more digits: with `-#`, `SW005-1` and `SW005-2` follow the rule `SW{n}`, both count as number 5 and keep their ending when suggested again. New names are suggested without the ending. |
| IP pattern | *From primary IP* only: a mask such as `*.*.*.N` (the octet marked N is the number) or a regular expression with one group, such as `\.([0-9]+)$`. |
| Enforcement | *Off*, *Warn* (default) or *Refuse*, see above. |

The rule form shows only the number fields that apply to the number source
you pick.

### Reserving names

*Reserve names* on a rule page takes the next names of the rule before
their devices (or virtual machines, racks) exist in NetBox, for labels or an
order. Pick how many, the values the names are built from (such as the site
and rack; values the rule's conditions name only one of are filled in), and
optionally a day the reservation expires and a description. The rule page
lists the reserved names; *Free selected* gives them back.

While a name is reserved, nobody else gets its number: not the add form,
not the API, not a name typed under *Refuse*. Saving an object with the
reserved name (type it into the name field) uses the reservation up. After
the expiry day the number is free again with gap filling on; without gap
filling it is never handed out again, like a deleted device's. Rules that
read the number from the IP can't reserve names.

### Preview

Under the template, the rule form shows what names look like
(`AMS1-SW###-[rack]`) and the names the rule would give the first ten of
its devices, and updates as you type. Pick a device in *Try on device* to
see the name it would get; the preview also says when the device doesn't
match the rule's conditions or another rule names it first. Nothing is
saved, reserved or renamed: the preview only shows the rule as the form has
it, before you save.

### Templates

Literal text, the number and values of the device in braces. The rule form
links to a reference page in NetBox (*All values and filters*) with the
same lists as below.

| Part | Gives |
| --- | --- |
| `SW-` | the text as written |
| `{n}` | the number, padded to the rule's digits |
| `{a-z}`, `{A-Z}` | the number as one letter instead, `a` (1) to `z` (26), in lower or upper case. A template has one counter at most: `{n}`, `{a-z}` or `{A-Z}` |
| `{site.name}`, `{site.slug}`, `{site.facility}` | values of the device's site |
| `{location.name}`, `{rack.name}`, `{tenant.slug}`, `{platform.name}` | values of other objects the device is in or has |
| `{role.name}`, `{role.parent.name}` | the role, or its parent (Switch for Switch / Access) |
| `{device_type.model}`, `{manufacturer.name}` | the hardware |
| `{region.name}`, `{site_group.slug}` | the site's region or group (`parent` works here too) |
| `{site.cf.code}`, `{cf.code}` | a custom field of the site, or of the device itself |
| `{device.serial}`, `{device.asset_tag}` | the device's own values |
| `{{`, `}}` | literal braces |

Virtual machines have `{site.…}`, `{region.…}`, `{site_group.…}`,
`{cluster.name}`, `{cluster_type.slug}`, `{cluster_group.slug}`,
`{role.…}`, `{vm_type.slug}`, `{tenant.…}`, `{platform.…}` and
`{vm.serial}`. Racks have `{site.…}`, `{region.…}`, `{site_group.…}`,
`{location.…}`, `{role.…}` (the rack role), `{rack_type.model}`,
`{manufacturer.…}`, `{tenant.…}` and `{rack.facility_id}`,
`{rack.serial}`, `{rack.asset_tag}`. The reference page has a list per
kind.

Filters change a value, from left to right: `{site.name|first:2|upper}`. To apply one to the
whole name instead, put it in the rule's *Filters for the whole name*.

| Filter | Does |
| --- | --- |
| `upper`, `lower` | changes case |
| `first:N`, `last:N` | keeps the first or last N characters |
| `ascii` | removes accents (Zürich → Zurich) |
| `alnum` | keeps only letters and digits |
| `nospace` | removes spaces |
| `replace:old:new` | replaces text (`replace: :-`; leave `new` out to remove) |
| `default:X` | X when the value is empty |
| `before:X`, `after:X` | adds X before or after the value, only when there is one (`{rack.name\|before:-}`) |
| `optional` | leaves the part out when it is empty |

A value that is empty and not `optional` (or `default`) makes the name wait,
like the rule's *Wait for* fields: under the name the device form shows the
rule, what names look like (`AMS1-SW###-[Rack]`) and what it still waits
for. A device saved
without that value is saved without a name, unless the rule refuses names
that don't fit. Virtual machines and racks can't be saved without a name, so
for them the missing value is an error until it is set (or a name is typed).

### Examples

| Devices | Template | Names |
| --- | --- | --- |
| Switches, with the rack | `{site.slug\|upper}-SW{n}-{rack.name}` | `AMS1-SW014-R01` |
| The same, rack optional | `{site.slug\|upper}-SW{n}{rack.name\|before:-\|optional}` | `AMS1-SW015`, `AMS1-SW016-R02` |
| Codes cut from names | `{region.name\|first:2\|upper}{site.name\|first:3\|upper}{role.parent.name\|first:3\|upper}{n}` | `NEAMSSWI001` (Netherlands, Amsterdam, Switch) |
| A tagged group (tag `lab`) | `LAB-{device_type.model}-{n}` | `LAB-C9300-001` |
| Printers, 4 digits | `{site.slug\|upper}-PRN{n}` | `AMS1-PRN0001` |
| Numbered by IP | `{site.slug}-sw{n}`, mask `*.*.*.N` | `ams1-sw006` for 10.0.0.6 |
| Virtual machines per cluster | `{cluster.name\|upper}-VM{n}` | `PROD-VM001` |
| Racks per site, 2 digits | `{site.slug\|upper}-R{n}` | `AMS1-R01` |
| Devices per rack, by letter | `{rack.name}{a-z}` | `R07a`, `R07b`, `R12a` |

Devices, virtual machines and racks count separately: a rack named
`AMS1-R01` doesn't take number 1 from devices named `AMS1-R…`. Racks can't
take their number from an IP (they have none).

## REST API

- `/api/plugins/naming-convention/rules/`: the rules (create, read, update,
  delete), like any NetBox object.
- `POST /api/plugins/naming-convention/suggest/`: send `object_type`
  (`device`, the default, `virtualmachine` or `rack`) and the object's values
  (`site`, `role`, `rack`, `cluster`, `device_type`, `tags` as ids, ...; or
  `id` for an existing one) and get the rule, the name, the number and the
  values it still waits for. Saves and reserves nothing. Needs permission to
  add or change that kind of object.
- `POST /api/plugins/naming-convention/reserve/`: reserve the next names
  (see *Reserving names*). Send the values like for `suggest`, plus `count`
  (default 1, at most 100), `expires` (a date), `description` and
  optionally `rule` (an id; by default the rule that matches the values).
  Returns the reserved names.
- `/api/plugins/naming-convention/reservations/`: the reserved names (list,
  read, delete). Deleting one frees its name.
- `POST /api/dcim/devices/`, `/api/virtualization/virtual-machines/` and
  `/api/dcim/racks/` without a `name` get the rule's name, as in the web UI.
  For virtual machines and racks without a rule NetBox still requires a name.
- CSV import fills in names of devices only; NetBox's import form requires a
  name for virtual machines and racks.

## With netbox-change-approval

Naming rules are ordinary NetBox objects, so changes to them need approval
like changes to any other object. A new device is written at once by
change-approval (marked pending), so it gets its name and number right
away; a rename waits for approval. While the request is open the number
counts as used. If the request is rejected, withdrawn, sent back or expires,
the device is removed and its number goes back to the series: the next
device gets it, even with gap filling off and even when later numbers were
handed out meanwhile. Above the changes, the change request
page says whether the name was filled in by the rule, follows it, or
doesn't (and what the rule suggests). The plugin's own records (numbers handed out, names
given) are never gated.

## License

Apache License 2.0. See [LICENSE](LICENSE).
