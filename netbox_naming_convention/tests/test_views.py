"""Web pages: rules, the device form helper, the device panel, CSV import."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.choices import DeviceStatusChoices
from dcim.models import Device

from ..models import NamingRule
from .utils import NetBoxData

URL = 'plugins:netbox_naming_convention:'


@override_settings(LOGIN_REQUIRED=True, EXEMPT_VIEW_PERMISSIONS=['*'])
class ViewTests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.tampere], name='Tampere switches')
        cls.user = get_user_model().objects.create(username='admin', is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def test_rule_pages(self):
        self.device(rack=self.jk8)
        Device.objects.create(name='old-switch', site=self.tampere, role=self.access, device_type=self.c9300,
                              rack=self.jk8)
        self.assertEqual(self.client.get(reverse(URL + 'namingrule_list')).status_code, 200)
        page = self.client.get(self.switches.get_absolute_url())
        self.assertContains(page, 'FITASWI002_JK8')  # next name of the series
        self.assertContains(page, 'old-switch')  # does not follow the rule
        self.assertEqual(self.client.get(reverse(URL + 'namingrule_add')).status_code, 200)

    def test_rule_form(self):
        response = self.client.post(reverse(URL + 'namingrule_add'), {
            'name': 'Printers', 'template': 'FITAPRN{n}', 'priority': 100, 'enabled': 'on',
            'number_source': 'sequence', 'number_digits': 3, 'number_first': 1, 'number_scope': 'shared',
            'enforcement': 'warn', 'tag_match': 'all',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'needs at least one role')
        response = self.client.post(reverse(URL + 'namingrule_add'), {
            'name': 'Printers', 'template': 'FITAPRN{n}', 'priority': 100, 'enabled': 'on',
            'roles': [self.printer.pk], 'number_source': 'sequence', 'number_digits': 3, 'number_first': 1,
            'number_scope': 'shared', 'enforcement': 'warn', 'tag_match': 'all',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(NamingRule.objects.filter(name='Printers').exists())

    def test_device_form_has_the_helper(self):
        page = self.client.get(reverse('dcim:device_add'))
        self.assertContains(page, "var MODE = 'add'")
        device = self.device(rack=self.jk8)
        page = self.client.get(reverse('dcim:device_edit', args=[device.pk]))
        self.assertContains(page, "var MODE = 'edit'")
        self.assertNotContains(self.client.get(reverse('dcim:site_add')), 'var MODE')

    def test_device_form_helper_can_be_turned_off(self):
        plugins_config = {**settings.PLUGINS_CONFIG, 'netbox_naming_convention': {
            **settings.PLUGINS_CONFIG.get('netbox_naming_convention', {}), 'device_form': False,
        }}
        with override_settings(PLUGINS_CONFIG=plugins_config):
            self.assertNotContains(self.client.get(reverse('dcim:device_add')), 'var MODE')

    def test_device_form_without_name(self):
        response = self.client.post(reverse('dcim:device_add'), {
            'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.jk8.pk,
            'status': DeviceStatusChoices.STATUS_ACTIVE, 'airflow': '', 'face': '',
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        self.assertEqual(Device.objects.get().name, 'FITASWI001_JK8')

    def test_device_form_with_the_rules_name_takes_a_free_number(self):
        # The form showed FITASWI001_JK8, but someone saved that number meanwhile.
        self.device(rack=self.jk8)
        response = self.client.post(reverse('dcim:device_add'), {
            'name': 'FITASWI001_JK8', '_naming_auto': '1',
            'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.jk8.pk,
            'status': DeviceStatusChoices.STATUS_ACTIVE,
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        self.assertTrue(Device.objects.filter(name='FITASWI002_JK8').exists())

    def test_device_form_typed_name_is_kept(self):
        response = self.client.post(reverse('dcim:device_add'), {
            'name': 'my-switch', 'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk,
            'rack': self.jk8.pk, 'status': DeviceStatusChoices.STATUS_ACTIVE,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Device.objects.filter(name='my-switch').exists())

    def test_device_panel(self):
        device = self.device(rack=self.jk8)
        page = self.client.get(device.get_absolute_url())
        self.assertContains(page, 'follows the rule')
        device.rack = self.jk9
        device.save()
        page = self.client.get(device.get_absolute_url())
        self.assertContains(page, 'does not follow the rule')
        self.assertContains(page, 'FITASWI001_JK9')

    def test_csv_import_without_names(self):
        csv = 'site,role,device_type,manufacturer,rack,status\n' + '\n'.join(
            f'Tampere,Access,C9300-48P,Cisco,{rack},active' for rack in ('JK8', 'JK9')
        )
        response = self.client.post(reverse('dcim:device_bulk_import'), {'data': csv, 'format': 'csv',
                                                                         'csv_delimiter': ','})
        self.assertEqual(response.status_code, 302, response.content[:3000])
        self.assertEqual(sorted(Device.objects.values_list('name', flat=True)),
                         ['FITASWI001_JK8', 'FITASWI002_JK9'])
