"""Shared test data: a Utrecht site with switches and routers."""
from dcim.models import Device, DeviceRole, DeviceType, Manufacturer, Rack, Region, Site
from extras.models import Tag

from .. import integrations
from ..models import NamingRule


class NetBoxData:
    """
    Test data and helpers. With netbox-change-approval installed, the tests
    that are not about it write as an approved change would, so its gate
    stays out of the way (test_change_approval.py sets gated=True).
    """
    gated = False

    @classmethod
    def setUpClass(cls):
        cls._ungated = None
        if not cls.gated and integrations.has_change_approval():
            from netbox_change_approval.context import applying_change_on

            cls._ungated = applying_change_on()
            cls._ungated.__enter__()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls._ungated is not None:
            cls._ungated.__exit__(None, None, None)

    @classmethod
    def make_netbox(cls):
        cls.holland = Region.objects.create(name='Holland', slug='holland')
        cls.utrecht = Site.objects.create(name='Utrecht', slug='utrecht', region=cls.holland)
        cls.nijmegen = Site.objects.create(name='Nijmegen', slug='nijmegen', region=cls.holland)
        cls.ra8 = Rack.objects.create(name='RA8', site=cls.utrecht)
        cls.ra9 = Rack.objects.create(name='RA9', site=cls.utrecht)
        cls.switch = DeviceRole.objects.create(name='Switch', slug='switch')
        cls.access = DeviceRole.objects.create(name='Access', slug='access', parent=cls.switch)
        cls.router = DeviceRole.objects.create(name='Router', slug='router')
        cls.printer = DeviceRole.objects.create(name='Printer', slug='printer')
        maker = Manufacturer.objects.create(name='Cisco', slug='cisco')
        cls.c9300 = DeviceType.objects.create(manufacturer=maker, model='C9300-48P', slug='c9300-48p')
        cls.lab = Tag.objects.create(name='lab', slug='lab')

    @classmethod
    def rule(cls, roles=(), device_types=(), sites=(), match_tags=(), **fields):
        fields.setdefault('name', f'Rule {NamingRule.objects.count() + 1}')
        fields.setdefault('template', 'NL{site.name|first:2|upper}{role.parent.name|first:3|upper}{n}_{rack.name}')
        rule = NamingRule.objects.create(**fields)
        rule.roles.set(roles)
        rule.device_types.set(device_types)
        rule.sites.set(sites)
        rule.match_tags.set(match_tags)
        return rule

    def device(self, name=None, site=None, role=None, rack=None, save=True, tags=(), **fields):
        device = Device(
            name=name, site=site or self.utrecht, role=role or self.access, device_type=self.c9300,
            rack=rack, **fields,
        )
        if tags:
            device._m2m_values = {'tags': list(tags)}
        if save:
            device.full_clean()
            device.save()
            if tags:
                device.tags.set(tags)
        return device
