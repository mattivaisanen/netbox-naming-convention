"""Web pages: rules, the device form helper, the device panel, CSV import."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.choices import DeviceStatusChoices
from dcim.models import Device

from core.models import ObjectChange

from .. import reference, template
from ..kinds import KINDS
from ..models import AssignedName, NamingRule
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

    def test_rule_form_shows_the_fields_of_its_number_source(self):
        url = reverse(URL + 'namingrule_add')
        page = self.client.get(url)
        self.assertContains(page, 'id="id_number_first"')
        self.assertContains(page, 'id="id_fill_gaps"')
        self.assertNotContains(page, 'id="id_ip_pattern"')
        self.assertContains(page, 'hx-get')  # number source redraws the form
        self.assertContains(page, reverse(URL + 'reference'))  # template help links the reference
        page = self.client.get(url, {'number_source': 'ip'}, headers={'HX-Request': 'true'})
        self.assertContains(page, 'id="id_ip_pattern"')
        self.assertContains(page, 'id="id_number_digits"')
        self.assertNotContains(page, 'id="id_number_first"')
        self.assertNotContains(page, 'id="id_skip_numbers"')
        self.assertNotContains(page, 'id="id_fill_gaps"')

    def test_changing_what_a_rule_names_drops_conditions_it_has_no_use_for(self):
        response = self.client.post(reverse(URL + 'namingrule_edit', args=[self.switches.pk]), {
            'name': 'Tampere racks', 'template': 'R{n}', 'priority': 100, 'enabled': 'on',
            'object_type': 'rack', 'sites': [self.tampere.pk], 'number_source': 'sequence', 'number_digits': 2,
            'number_first': 1, 'number_scope': 'shared', 'enforcement': 'warn', 'tag_match': 'all',
            'required_values': ['site'],
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        self.assertFalse(self.switches.roles.exists())  # racks have no device roles
        self.assertEqual(list(self.switches.sites.all()), [self.tampere])

    def test_reserve_names_from_the_rule_page(self):
        url = reverse(URL + 'namingrule_reserve', args=[self.switches.pk])
        page = self.client.get(url)
        self.assertContains(page, 'id="id_rack"')
        response = self.client.post(url, {'count': 2, 'site': self.tampere.pk, 'role': self.access.pk,
                                          'rack': self.jk8.pk})
        self.assertEqual(response.status_code, 302, response.content[:3000])
        page = self.client.get(self.switches.get_absolute_url())
        self.assertContains(page, 'FITASWI001_JK8')
        self.assertContains(page, 'FITASWI002_JK8')
        first = self.switches.reserved_names.first()
        self.client.post(reverse(URL + 'namingrule_unreserve', args=[self.switches.pk]), {'pk': [first.pk]})
        self.assertEqual(list(self.switches.reserved_names.values_list('name', flat=True)), ['FITASWI002_JK8'])

    def test_ip_rule_form_saves_without_the_sequence_fields(self):
        response = self.client.post(reverse(URL + 'namingrule_add'), {
            'name': 'By IP', 'template': 'sw{n}', 'priority': 100, 'enabled': 'on', 'roles': [self.router.pk],
            'number_source': 'ip', 'ip_pattern': '*.*.*.N', 'number_digits': 3, 'number_scope': 'shared',
            'enforcement': 'warn', 'tag_match': 'all',
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        self.assertEqual(NamingRule.objects.get(name='By IP').ip_pattern, '*.*.*.N')

    def test_reference_page(self):
        page = self.client.get(reverse(URL + 'reference'))
        self.assertEqual(page.status_code, 200)
        for name, _text, _example in reference.FILTERS:
            self.assertContains(page, name)
        self.assertContains(self.client.get(reverse(URL + 'reference'), {'object_type': 'rack'}), '{rack.facility_id}')

    def test_reference_lists_every_root_and_filter(self):
        listed = {name.split(':')[0] for name, _text, _example in reference.FILTERS}
        self.assertEqual(listed, set(template.FILTERS))
        for key, kind in KINDS.items():
            for root in kind.roots:
                examples = [example for example, _text in reference.VALUES[key]]
                self.assertTrue(any(example.startswith('{' + root + '.') for example in examples), (key, root))

    def test_device_form_helper_locks_names_that_follow_the_rule(self):
        page = self.client.get(reverse('dcim:device_add'))
        self.assertContains(page, "var LOCKED = 'yes'")
        named = self.device(rack=self.jk8)
        page = self.client.get(reverse('dcim:device_edit', args=[named.pk]))
        self.assertContains(page, "var LOCKED = 'yes'")
        typed = self.device(name='my-switch', rack=self.jk8)
        page = self.client.get(reverse('dcim:device_edit', args=[typed.pk]))
        self.assertContains(page, "var LOCKED = ''")

    def test_device_form_helper_needs_a_rule(self):
        NamingRule.objects.update(enabled=False)
        self.assertNotContains(self.client.get(reverse('dcim:device_add')), 'var MODE')

    def test_name_from_the_rule_is_recorded(self):
        response = self.client.post(reverse('dcim:device_add'), {
            'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.jk8.pk,
            'status': DeviceStatusChoices.STATUS_ACTIVE, 'changelog_message': 'New switch',
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        device = Device.objects.get()
        change = ObjectChange.objects.get(changed_object_id=device.pk, action='create')
        self.assertEqual(change.message, 'New switch | Name from naming rule "Tampere switches"')
        assigned = AssignedName.of(device).get()
        self.assertEqual((assigned.name, assigned.how, assigned.rule), ('FITASWI001_JK8', 'auto', self.switches))
        self.assertContains(self.client.get(device.get_absolute_url()), 'Filled in by the rule')

    def test_typed_name_is_not_recorded(self):
        self.client.post(reverse('dcim:device_add'), {
            'name': 'my-switch', 'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk,
            'rack': self.jk8.pk, 'status': DeviceStatusChoices.STATUS_ACTIVE,
        })
        device = Device.objects.get()
        self.assertFalse(AssignedName.objects.exists())
        self.assertEqual(ObjectChange.objects.get(changed_object_id=device.pk, action='create').message, '')

    def test_suggest_again_is_recorded(self):
        device = self.device(rack=self.jk8)
        form = {'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.jk9.pk,
                'status': DeviceStatusChoices.STATUS_ACTIVE}
        # A name typed by hand that happens to differ from the suggestion: not recorded.
        self.client.post(reverse('dcim:device_edit', args=[device.pk]), {
            **form, 'name': 'FITASWI005_JK9', '_naming_suggested': 'FITASWI001_JK9',
        })
        self.assertFalse(AssignedName.objects.filter(name='FITASWI005_JK9').exists())
        device.rack = self.jk8
        device.name = 'FITASWI001_JK8'
        device.save()
        response = self.client.post(reverse('dcim:device_edit', args=[device.pk]), {
            **form, 'name': 'FITASWI001_JK9', '_naming_suggested': 'FITASWI001_JK9',
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        device.refresh_from_db()
        self.assertEqual(device.name, 'FITASWI001_JK9')
        self.assertEqual(AssignedName.of(device).get(name='FITASWI001_JK9').how, 'suggested')
        change = ObjectChange.objects.filter(changed_object_id=device.pk, action='update').latest('time')
        self.assertEqual(change.message, 'Name suggested by naming rule "Tampere switches"')

    def test_rename_devices_to_the_rule(self):
        one = self.device(name='old-1', rack=self.jk8)
        two = self.device(name='old-2', rack=self.jk9)
        page = self.client.get(self.switches.get_absolute_url())
        self.assertContains(page, reverse(URL + 'namingrule_rename', args=[self.switches.pk]))
        self.assertContains(page, f'name="pk" value="{one.pk}"')  # the objects can be ticked
        page = self.client.post(reverse(URL + 'namingrule_rename', args=[self.switches.pk]),
                                {'pk': [one.pk, two.pk]})
        self.assertEqual(page.status_code, 200)
        data = page.context['data']
        self.assertEqual(data, f'id,name\n{one.pk},FITASWI001_JK8\n{two.pk},FITASWI002_JK9\n')
        # The confirm button sends it to NetBox's device import.
        response = self.client.post(reverse('dcim:device_bulk_import'), {
            'data': data, 'format': 'csv', 'csv_delimiter': ',', 'import_method': 'direct', '_naming_rename': '1',
        })
        self.assertEqual(response.status_code, 302, response.content[:3000])
        one.refresh_from_db()
        two.refresh_from_db()
        self.assertEqual((one.name, two.name), ('FITASWI001_JK8', 'FITASWI002_JK9'))
        self.assertEqual(AssignedName.of(one).get().how, 'suggested')

    def test_naming_report(self):
        follows = self.device(rack=self.jk8)
        drifted = self.device(name='old-1', rack=self.jk9)
        # Made before the rule (bulk_create skips the plugin's save hooks).
        unnamed, = Device.objects.bulk_create([self.device(rack=self.jk8, save=False)])
        router = self.device(name='r1', role=self.router)
        url = reverse(URL + 'report')
        page = self.client.get(url)
        report = page.context['report']
        self.assertEqual(report.counts, {'follows': 1, 'drifted': 1, 'unnamed': 1, 'no_rule': 1})
        self.assertEqual([(entry.rule, entry.count, entry.drifted) for entry in report.rules],
                         [(self.switches, 3, 2)])
        self.assertEqual([obj.pk for obj in report.shown], [drifted.pk])
        self.assertContains(page, 'FITASWI002_JK9')
        self.assertContains(page, f'name="pk" value="{drifted.pk}"')
        page = self.client.get(url, {'show': 'no_rule'})
        self.assertEqual([obj.pk for obj in page.context['report'].shown], [router.pk])
        self.assertNotContains(page, 'Rename selected')
        # Ticked objects are renamed by their own rules; one without a rule is left alone.
        page = self.client.post(reverse(URL + 'report_rename') + '?object_type=device',
                                {'pk': [drifted.pk, unnamed.pk, router.pk, follows.pk]})
        self.assertEqual(page.context['data'], f'id,name\n{drifted.pk},FITASWI002_JK9\n{unnamed.pk},FITASWI003_JK8\n')
        self.assertEqual([obj for obj, _reason in page.context['skipped']], [router])
        # Racks have their own tab.
        page = self.client.get(url, {'object_type': 'rack'})
        self.assertEqual(page.context['report'].counts['no_rule'], 2)

    def test_rule_preview(self):
        named = self.device(rack=self.jk8)
        Device.objects.create(name='old-switch', site=self.tampere, role=self.access, device_type=self.c9300,
                              rack=self.jk9)
        self.assertContains(self.client.get(reverse(URL + 'namingrule_add')), 'id="naming-preview"')
        url = reverse(URL + 'namingrule_preview')
        form = {
            'name': 'Tampere switches', 'priority': 100, 'roles': [self.switch.pk], 'sites': [self.tampere.pk],
            'number_source': 'sequence', 'number_digits': 3, 'number_first': 1, 'number_scope': 'shared',
            'enforcement': 'warn', 'tag_match': 'all', 'required_values': ['site', 'role', 'device_type'],
        }
        # Editing a rule: its devices with the names the new template gives them.
        page = self.client.post(f'{url}?rule={self.switches.pk}', {**form, 'template': 'SW-{rack.name}-{n}'})
        self.assertEqual([row['name'] for row in page.context['rows']], ['SW-JK8-001', 'SW-JK9-001'])
        self.assertEqual(page.context['rows'][0]['object'], named)
        self.assertEqual(self.switches.template, NamingRule.objects.get(pk=self.switches.pk).template)
        # A new rule, tried on a device of another rule.
        page = self.client.post(url, {
            **form, 'name': 'New', 'priority': 200, 'template': 'X{n}', 'preview_object': named.pk,
        })
        self.assertEqual(page.context['tried']['name'], 'X001')
        self.assertContains(page, 'names this device first')
        # A broken template only shows the error.
        page = self.client.post(url, {**form, 'template': 'SW{nope}'})
        self.assertTrue(page.context['errors'])
