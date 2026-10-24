"""Rules for virtual machines and racks: naming on save, the API, what a rule of each kind may use."""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.models import Rack, RackRole
from virtualization.models import Cluster, ClusterType, VirtualMachine

from ..models import AssignedName, NamingRule, NamingSeries
from .utils import NetBoxData

SUGGEST = 'plugins-api:netbox_naming_convention-api:suggest'


@override_settings(LOGIN_REQUIRED=True, EXEMPT_VIEW_PERMISSIONS=['*'])
class KindTests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        kind = ClusterType.objects.create(name='VMware', slug='vmware')
        cls.cluster = Cluster.objects.create(name='prod', type=kind)
        cls.other_cluster = Cluster.objects.create(name='lab', type=kind)
        cls.vms = NamingRule.objects.create(
            name='VMs', object_type='virtualmachine', template='{cluster.name|upper}-VM{n}',
        )
        cls.vms.clusters.set([cls.cluster])
        cls.storage = RackRole.objects.create(name='Storage', slug='storage')
        cls.racks = NamingRule.objects.create(
            name='Racks', object_type='rack', template='{site.slug|upper}-R{n}', number_digits=2,
        )
        cls.racks.rack_roles.set([cls.storage])
        cls.user = get_user_model().objects.create(username='admin', is_superuser=True)

    def test_virtual_machines_are_named(self):
        # Saved without validating (a script): named on save.
        first = VirtualMachine(cluster=self.cluster)
        first.save()
        self.client.force_login(self.user)
        # The add form sends the name the rule filled in, marked as the rule's.
        response = self.client.post(reverse('virtualization:virtualmachine_add'), {
            'name': 'PROD-VM001', '_naming_auto': '1', 'cluster': self.cluster.pk, 'status': 'active',
            'start_on_boot': 'off',
        })
        errors = response.context['form'].errors if response.status_code == 200 else None
        self.assertEqual(response.status_code, 302, errors)
        second = VirtualMachine.objects.exclude(pk=first.pk).get()
        self.assertEqual((first.name, second.name), ('PROD-VM001', 'PROD-VM002'))
        self.assertEqual(AssignedName.lookup(first, first.name).how, 'auto')
        self.assertEqual(NamingSeries.objects.get(key='virtualmachine:prod-vm').high_water, 2)
        # Only VMs of the rule's cluster; NetBox wants a name for the others.
        with self.assertRaises(ValidationError):
            VirtualMachine(cluster=self.other_cluster).full_clean()
        first.delete()
        self.assertFalse(AssignedName.objects.filter(name='PROD-VM001').exists())

    def test_racks_count_apart_from_devices(self):
        self.device(name='TAMPERE-R01', rack=self.jk8)
        rack = Rack(site=self.tampere, role=self.storage)
        rack.save()
        # A device's name is not a rack's number.
        self.assertEqual(rack.name, 'TAMPERE-R01')

    def test_api_names_virtual_machines_and_racks(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('virtualization-api:virtualmachine-list'), {'cluster': self.cluster.pk},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'PROD-VM001')
        response = self.client.post(
            reverse('dcim-api:rack-list'), {'site': self.tampere.pk, 'role': self.storage.pk},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()['name'], 'TAMPERE-R01')
        # Without a rule a name is still required.
        response = self.client.post(
            reverse('dcim-api:rack-list'), {'site': self.tampere.pk}, content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse(SUGGEST), {'object_type': 'rack', 'site': self.tampere.pk, 'role': self.storage.pk},
            content_type='application/json',
        )
        self.assertEqual(response.json()['name'], 'TAMPERE-R02')

    def test_a_rule_uses_only_what_its_kind_has(self):
        def errors(**fields):
            rule = NamingRule(name='x', **fields)
            try:
                rule.full_clean()
            except ValidationError as e:
                return set(e.message_dict)
            return set()

        self.assertEqual(errors(object_type='rack', template='R{n}', number_source='ip', ip_pattern='*.*.*.N'),
                         {'number_source'})
        self.assertEqual(errors(object_type='rack', template='{device_type.model}{n}'), {'template'})
        self.assertEqual(errors(object_type='virtualmachine', template='VM{n}', statuses=['inventory']),
                         {'statuses'})
        self.assertEqual(errors(object_type='virtualmachine', template='{vm.serial}{n}'), set())
        # A VM rule left at the device default waits for nothing a VM lacks.
        rule = NamingRule(name='y', object_type='virtualmachine', template='VM{n}')
        rule.full_clean()
        self.assertEqual(rule.required_values, [])

    def test_rule_form_shows_the_conditions_of_its_kind(self):
        self.client.force_login(self.user)
        url = reverse('plugins:netbox_naming_convention:namingrule_add')
        page = self.client.get(url, {'object_type': 'rack'})
        self.assertContains(page, 'id="id_rack_roles"')
        self.assertNotContains(page, 'id="id_device_types"')
        self.assertNotContains(page, 'id="id_ip_pattern"')
        Rack(site=self.tampere, role=self.storage).save()
        page = self.client.get(self.racks.get_absolute_url())
        self.assertContains(page, 'Rack roles')
        self.assertContains(page, 'TAMPERE-R02')  # next name of the series
