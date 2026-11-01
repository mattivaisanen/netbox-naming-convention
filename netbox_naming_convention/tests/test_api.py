"""REST API: devices created without a name, the suggest endpoint, rules."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.models import Device

import datetime

from ..models import EnforcementChoices, NamingRule, ReservedName
from .utils import NetBoxData

SUGGEST = 'plugins-api:netbox_naming_convention-api:suggest'
RULES = 'plugins-api:netbox_naming_convention-api:namingrule-list'
RESERVE = 'plugins-api:netbox_naming_convention-api:reserve'
RESERVATIONS = 'plugins-api:netbox_naming_convention-api:reservedname-list'
RESERVATION = 'plugins-api:netbox_naming_convention-api:reservedname-detail'


@override_settings(LOGIN_REQUIRED=True, EXEMPT_VIEW_PERMISSIONS=['*'])
class APITests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.utrecht])
        cls.user = get_user_model().objects.create(username='admin', is_superuser=True)

    def setUp(self):
        self.client.force_login(self.user)

    def post(self, url, data):
        return self.client.post(url, data, content_type='application/json')

    def device_data(self, **extra):
        return {'site': self.utrecht.pk, 'role': self.access.pk, 'device_type': self.c9300.pk,
                'rack': self.ra8.pk, **extra}

    def test_create_without_name(self):
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'NLUTSWI001_RA8')

    def test_bulk_create_without_names(self):
        response = self.post(reverse('dcim-api:device-list'), [self.device_data(), self.device_data(rack=self.ra9.pk)])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([d['name'] for d in response.json()], ['NLUTSWI001_RA8', 'NLUTSWI002_RA9'])

    def test_reserved_names_are_skipped_and_used_up(self):
        response = self.post(reverse(RESERVE), self.device_data(count=2, description='order 42'))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([r['name'] for r in response.json()], ['NLUTSWI001_RA8', 'NLUTSWI002_RA8'])
        # Nobody else gets the reserved numbers.
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.json()['name'], 'NLUTSWI003_RA8')
        # A rule that refuses other names accepts the reserved one, and saving it uses the reservation up.
        self.switches.enforcement = EnforcementChoices.REFUSE
        self.switches.save()
        response = self.post(reverse('dcim-api:device-list'), self.device_data(name='NLUTSWI002_RA8'))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(list(ReservedName.objects.values_list('name', flat=True)), ['NLUTSWI001_RA8'])
        response = self.post(reverse('dcim-api:device-list'), self.device_data(name='NLUTSWI001_RA9'))
        self.assertEqual(response.status_code, 400)  # number 1 is reserved
        self.assertEqual(self.client.get(reverse(RESERVATIONS)).json()['count'], 1)

    def test_expired_reservations_free_their_number(self):
        self.switches.fill_gaps = True
        self.switches.save()
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        response = self.post(reverse(RESERVE), self.device_data(expires=yesterday.isoformat()))
        self.assertEqual(response.json()[0]['name'], 'NLUTSWI001_RA8')
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.json()['name'], 'NLUTSWI001_RA8')
        self.assertFalse(ReservedName.objects.exists())

    def test_freed_reservations_give_their_numbers_back(self):
        # Gap filling is off: freed numbers still come back before new ones.
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        self.post(reverse(RESERVE), self.device_data(expires=yesterday.isoformat()))
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.json()['name'], 'NLUTSWI001_RA8')  # the expired one
        kept = self.post(reverse(RESERVE), self.device_data()).json()[0]
        self.client.delete(reverse(RESERVATION, args=[kept['id']]))
        response = self.post(reverse('dcim-api:device-list'), self.device_data())
        self.assertEqual(response.json()['name'], kept['name'])  # the deleted one

    def test_create_with_tags_rule(self):
        self.rule(roles=[self.router], match_tags=[self.lab], template='NLUTROT{n}', priority=1)
        response = self.post(reverse('dcim-api:device-list'), self.device_data(
            role=self.router.pk, tags=[{'name': 'lab'}],
        ))
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'NLUTROT001')

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
        self.assertEqual(data['name'], 'NLUTSWI001_RA8')
        self.assertTrue(data['ready'])
        self.assertEqual(data['rule']['id'], self.switches.pk)
        self.assertFalse(Device.objects.exists(), 'suggesting saves nothing')

    def test_suggest_waiting(self):
        data = self.post(reverse(SUGGEST), self.device_data(rack=None)).json()
        self.assertEqual((data['ready'], data['missing']), (False, ['rack']))

    def test_suggest_no_rule(self):
        data = self.post(reverse(SUGGEST), self.device_data(site=self.nijmegen.pk)).json()
        self.assertIsNone(data['rule'])

    def test_suggest_for_existing_device_keeps_its_number(self):
        device = self.device(rack=self.ra8)
        self.device(rack=self.ra8)
        data = self.post(reverse(SUGGEST), {'device': device.pk, 'rack': self.ra9.pk}).json()
        self.assertEqual(data['name'], 'NLUTSWI001_RA9')
        self.assertEqual(data['current'], 'NLUTSWI001_RA8')

    def test_suggest_for_existing_device_waits_for_a_cleared_field(self):
        # The device form sends a cleared field as null; the saved rack must not be used.
        device = self.device(rack=self.ra8)
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
