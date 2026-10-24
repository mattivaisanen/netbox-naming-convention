"""REST API: devices created without a name, the suggest endpoint, rules."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.models import Device

from ..models import NamingRule
from .utils import NetBoxData

SUGGEST = 'plugins-api:netbox_naming_convention-api:suggest'
RULES = 'plugins-api:netbox_naming_convention-api:namingrule-list'


@override_settings(LOGIN_REQUIRED=True, EXEMPT_VIEW_PERMISSIONS=['*'])
class APITests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.tampere])
        cls.user = get_user_model().objects.create(username='admin', is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, url, data):
        return self.client.post(url, data, content_type='application/json')

    def device_data(self, **extra):
        return {'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk,
                'rack': self.jk8.pk, **extra}

    def test_create_without_name(self):
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'FITASWI001_JK8')

    def test_bulk_create_without_names(self):
        response = self.post(reverse('dcim-api:device-list'), [self.device_data(), self.device_data(rack=self.jk9.pk)])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([d['name'] for d in response.json()], ['FITASWI001_JK8', 'FITASWI002_JK9'])

    def test_create_with_tags_rule(self):
        self.rule(roles=[self.router], match_tags=[self.ot], template='FITAROT{n}', priority=1)
        response = self.post(reverse('dcim-api:device-list'), self.device_data(
            role=self.router.pk, tags=[{'name': 'ot'}],
        ))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'FITAROT001')

    def test_create_with_name_keeps_it(self):
        response = self.post(reverse('dcim-api:device-list'), self.device_data(name='mine'))
        self.assertEqual(response.json()['name'], 'mine')

    def test_full_series_is_a_400(self):
        self.switches.number_last = 0
        self.switches.number_first = 0
        self.switches.skip_numbers = '0'
        self.switches.save()
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.status_code, 400, response.content)

    def test_suggest(self):
        data = self.post(reverse(SUGGEST), self.device_data()).json()
        self.assertEqual(data['name'], 'FITASWI001_JK8')
        self.assertTrue(data['ready'])
        self.assertEqual(data['rule']['id'], self.switches.pk)
        self.assertFalse(Device.objects.exists(), 'suggesting saves nothing')

    def test_suggest_waiting(self):
        data = self.post(reverse(SUGGEST), self.device_data(rack=None)).json()
        self.assertEqual((data['ready'], data['missing']), (False, ['rack']))

    def test_suggest_no_rule(self):
        data = self.post(reverse(SUGGEST), self.device_data(site=self.helsinki.pk)).json()
        self.assertIsNone(data['rule'])

    def test_suggest_for_existing_device_keeps_its_number(self):
        device = self.device(rack=self.jk8)
        self.device(rack=self.jk8)
        data = self.post(reverse(SUGGEST), {'device': device.pk, 'rack': self.jk9.pk}).json()
        self.assertEqual(data['name'], 'FITASWI001_JK9')
        self.assertEqual(data['current'], 'FITASWI001_JK8')

    def test_suggest_for_existing_device_waits_for_a_cleared_field(self):
        # The device form sends a cleared field as null; the saved rack must not be used.
        device = self.device(rack=self.jk8)
        data = self.post(reverse(SUGGEST), {'device': device.pk, 'rack': None}).json()
        self.assertEqual((data['ready'], data['missing']), (False, ['rack']))

    def test_suggest_needs_device_permission(self):
        user = get_user_model().objects.create(username='viewer')
        self.client.force_login(user)
        self.assertEqual(self.post(reverse(SUGGEST), self.device_data()).status_code, 403)

    def test_rule_needs_role_or_type(self):
        response = self.post(reverse(RULES), {'name': 'x', 'template': 'X{n}'})
        self.assertEqual(response.status_code, 400)
        response = self.post(reverse(RULES), {'name': 'x', 'template': 'X{n}', 'roles': [self.printer.pk]})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(NamingRule.objects.get(name='x').roles.get(), self.printer)

    def test_rule_with_bad_template(self):
        response = self.post(reverse(RULES), {'name': 'x', 'template': '{site}', 'roles': [self.printer.pk]})
        self.assertEqual(response.status_code, 400)
