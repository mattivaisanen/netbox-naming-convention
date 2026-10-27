"""With netbox-change-approval installed: naming follows its approvals."""
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from dcim.choices import DeviceStatusChoices
from dcim.models import Device

from .. import integrations
from ..models import NamingSeries
from .utils import NetBoxData


@skipUnless(integrations.has_change_approval(), 'netbox-change-approval is not installed')
@override_settings(LOGIN_REQUIRED=True, EXEMPT_VIEW_PERMISSIONS=['*'])
class ChangeApprovalTests(NetBoxData, TestCase):
    gated = True

    @classmethod
    def setUpTestData(cls):
        from core.models import ObjectType
        from users.models import Group, ObjectPermission

        cls.make_netbox()
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.utrecht], name='Utrecht switches')
        Group.objects.get_or_create(name='Change Approvers')
        cls.engineer = get_user_model().objects.create(username='engineer')
        # May change everything, but has no approval bypass.
        permission = ObjectPermission.objects.create(name='engineer', actions=['view', 'add', 'change', 'delete'])
        permission.object_types.set(ObjectType.objects.public())
        permission.users.add(cls.engineer)

    def setUp(self):
        self.client.force_login(self.engineer)

    def form(self, **extra):
        return {'site': self.utrecht.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.ra8.pk,
                'status': DeviceStatusChoices.STATUS_ACTIVE, **extra}

    def test_new_device_is_named_and_pending(self):
        from netbox_change_approval.models import ChangeRequest

        response = self.client.post(reverse('dcim:device_add'), self.form())
        self.assertEqual(response.status_code, 302, response.content[:3000])
        device = Device.objects.get()
        self.assertEqual(device.name, 'NLUTSWI001_RA8')
        self.assertTrue(ChangeRequest.objects.filter(object_id=device.pk, action='create', status='pending').exists())
        self.assertEqual(NamingSeries.objects.get(key='device:nlutswi').high_water, 1)
        change = ChangeRequest.objects.get(object_id=device.pk, action='create')
        page = self.client.get(change.get_absolute_url())
        self.assertContains(page, 'was filled in by the naming rule "Utrecht switches"')

    def add(self):
        response = self.client.post(reverse('dcim:device_add'), self.form())
        self.assertEqual(response.status_code, 302, response.content[:3000])
        return Device.objects.latest('pk')

    def test_rejected_device_gives_its_number_back(self):
        from netbox_change_approval.models import ChangeRequest

        self.add()
        rejected = self.add()
        self.assertEqual(rejected.name, 'NLUTSWI002_RA8')
        ChangeRequest.objects.get(object_id=rejected.pk, action='create').reject(None, 'No')
        self.assertFalse(Device.objects.filter(pk=rejected.pk).exists())
        self.assertEqual(self.add().name, 'NLUTSWI002_RA8')

    def test_number_rejected_after_a_later_one_comes_back(self):
        from netbox_change_approval.models import ChangeRequest

        first = self.add()
        self.add()
        ChangeRequest.objects.get(object_id=first.pk, action='create').retract(self.engineer)
        self.assertEqual(self.add().name, 'NLUTSWI001_RA8')
        self.assertEqual(self.add().name, 'NLUTSWI003_RA8')
        self.assertEqual(NamingSeries.objects.get(key='device:nlutswi').released, [])

    def test_deleted_approved_device_keeps_its_number(self):
        from netbox_change_approval.context import applying_change_on

        device = self.add()
        with applying_change_on():
            from netbox_change_approval.models import ChangeRequest
            ChangeRequest.objects.get(object_id=device.pk, action='create').apply()
            device.delete()
        self.assertEqual(self.add().name, 'NLUTSWI002_RA8')

    def test_rename_to_the_rules_name_shows_on_the_change_request(self):
        from netbox_change_approval.context import applying_change_on
        from netbox_change_approval.models import ChangeRequest

        with applying_change_on():
            device = Device.objects.create(name='NLUTSWI001_RA8', site=self.utrecht, role=self.access,
                                           device_type=self.c9300, rack=self.ra8)
        self.client.post(reverse('dcim:device_edit', args=[device.pk]), self.form(
            name='NLUTSWI001_RA9', rack=self.ra9.pk, _naming_suggested='NLUTSWI001_RA9',
        ))
        change = ChangeRequest.objects.get(object_id=device.pk, action='update', status='pending')
        page = self.client.get(change.get_absolute_url())
        self.assertContains(page, 'follows the naming rule "Utrecht switches"')

    def test_typed_rename_shows_on_the_change_request(self):
        from netbox_change_approval.context import applying_change_on
        from netbox_change_approval.models import ChangeRequest

        with applying_change_on():
            device = Device.objects.create(name='NLUTSWI001_RA8', site=self.utrecht, role=self.access,
                                           device_type=self.c9300, rack=self.ra8)
        self.client.post(reverse('dcim:device_edit', args=[device.pk]), self.form(name='my-switch'))
        change = ChangeRequest.objects.get(object_id=device.pk, action='update', status='pending')
        page = self.client.get(change.get_absolute_url())
        self.assertContains(page, 'does not follow the naming rule "Utrecht switches"')
        self.assertContains(page, 'The rule suggests <strong>NLUTSWI001_RA8</strong>')

    def test_rename_waits_for_approval(self):
        from netbox_change_approval.models import ChangeRequest

        device = Device.objects.create(name='NLUTSWI001_RA8', site=self.utrecht, role=self.access,
                                       device_type=self.c9300, rack=self.ra8)
        response = self.client.post(reverse('dcim:device_edit', args=[device.pk]), self.form(
            name='NLUTSWI001_RA9', rack=self.ra9.pk,
        ))
        self.assertIn(response.status_code, (200, 302))
        device.refresh_from_db()
        self.assertEqual(device.name, 'NLUTSWI001_RA8')
        self.assertTrue(ChangeRequest.objects.filter(object_id=device.pk, action='update', status='pending').exists())

    def test_rule_changes_need_approval(self):
        from netbox_change_approval.models import ChangeRequest

        url = reverse('plugins:netbox_naming_convention:namingrule_edit', args=[self.switches.pk])
        self.client.post(url, {
            'name': 'Utrecht switches', 'template': 'X{n}', 'priority': 100, 'enabled': 'on',
            'roles': [self.switch.pk], 'sites': [self.utrecht.pk], 'number_source': 'sequence', 'number_digits': 3,
            'number_first': 1, 'number_scope': 'shared', 'enforcement': 'warn', 'tag_match': 'all',
        })
        self.switches.refresh_from_db()
        self.assertNotEqual(self.switches.template, 'X{n}')
        self.assertTrue(ChangeRequest.objects.filter(object_id=self.switches.pk, status='pending').exists())
