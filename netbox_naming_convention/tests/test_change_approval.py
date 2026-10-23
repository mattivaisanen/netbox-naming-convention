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
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.tampere], name='Tampere switches')
        Group.objects.get_or_create(name='Change Approvers')
        cls.engineer = get_user_model().objects.create(username='engineer')
        # May change everything, but has no approval bypass.
        permission = ObjectPermission.objects.create(name='engineer', actions=['view', 'add', 'change', 'delete'])
        permission.object_types.set(ObjectType.objects.public())
        permission.users.add(cls.engineer)

    def setUp(self):
        self.client.force_login(self.engineer)

    def form(self, **extra):
        return {'site': self.tampere.pk, 'role': self.access.pk, 'device_type': self.c9300.pk, 'rack': self.jk8.pk,
                'status': DeviceStatusChoices.STATUS_ACTIVE, **extra}

    def test_new_device_is_named_and_pending(self):
        from netbox_change_approval.models import ChangeRequest

        response = self.client.post(reverse('dcim:device_add'), self.form())
        self.assertEqual(response.status_code, 302, response.content[:3000])
        device = Device.objects.get()
        self.assertEqual(device.name, 'FITASWI001_JK8')
        self.assertTrue(ChangeRequest.objects.filter(object_id=device.pk, action='create', status='pending').exists())
        self.assertEqual(NamingSeries.objects.get(key='fitaswi').high_water, 1)

    def test_rename_waits_for_approval(self):
        from netbox_change_approval.models import ChangeRequest

        device = Device.objects.create(name='FITASWI001_JK8', site=self.tampere, role=self.access,
                                       device_type=self.c9300, rack=self.jk8)
        response = self.client.post(reverse('dcim:device_edit', args=[device.pk]), self.form(
            name='FITASWI001_JK9', rack=self.jk9.pk,
        ))
        self.assertIn(response.status_code, (200, 302))
        device.refresh_from_db()
        self.assertEqual(device.name, 'FITASWI001_JK8')
        self.assertTrue(ChangeRequest.objects.filter(object_id=device.pk, action='update', status='pending').exists())

    def test_rule_changes_need_approval(self):
        from netbox_change_approval.models import ChangeRequest

        url = reverse('plugins:netbox_naming_convention:namingrule_edit', args=[self.switches.pk])
        self.client.post(url, {
            'name': 'Tampere switches', 'template': 'X{n}', 'priority': 100, 'enabled': 'on',
            'roles': [self.switch.pk], 'sites': [self.tampere.pk], 'number_source': 'sequence', 'number_digits': 3,
            'number_first': 1, 'number_scope': 'shared', 'enforcement': 'warn', 'tag_match': 'all',
        })
        self.switches.refresh_from_db()
        self.assertNotEqual(self.switches.template, 'X{n}')
        self.assertTrue(ChangeRequest.objects.filter(object_id=self.switches.pk, status='pending').exists())
