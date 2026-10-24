"""Naming devices on save: numbers, series, enforcement, editing."""
import threading

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase

from dcim.choices import InterfaceTypeChoices
from dcim.models import Device, Interface
from ipam.models import IPAddress
from utilities.exceptions import AbortRequest

from ..models import EnforcementChoices, NamingRule, NamingSeries, NumberScopeChoices, NumberSourceChoices
from ..naming import suggest
from .utils import NetBoxData


class NamingTests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        cls.switches = cls.rule(roles=[cls.switch], sites=[cls.tampere], name='Tampere switches')

    def test_new_device_gets_the_rules_name(self):
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI001_JK8')
        self.assertEqual(self.device(rack=self.jk9).name, 'FITASWI002_JK9')

    def test_more_specific_rule_wins_on_equal_priority(self):
        # Named so it sorts before the tagged rule: the name must not decide.
        self.rule(roles=[self.switch], name='A switches', template='SW{n}')
        self.switches.delete()
        self.rule(roles=[self.switch], match_tags=[self.ot], name='OT switches', template='OT-SW{n}')
        self.assertEqual(self.device(rack=self.jk8, tags=[self.ot]).name, 'OT-SW001')
        self.assertEqual(self.device(rack=self.jk8).name, 'SW001')

    def test_priority_still_comes_first(self):
        self.switches.delete()
        self.rule(roles=[self.switch], name='General', template='SW{n}', priority=10)
        self.rule(roles=[self.switch], match_tags=[self.ot], name='OT switches', template='OT-SW{n}')
        self.assertEqual(self.device(rack=self.jk8, tags=[self.ot]).name, 'SW001')

    def test_rule_waits_for_its_required_values(self):
        self.assertEqual(self.switches.required_values, ['site', 'role', 'device_type'])
        self.switches.template = 'SW{n}'
        self.switches.required_values = ['site', 'role', 'device_type', 'rack']
        self.switches.save()
        waiting = suggest(self.device(save=False))
        self.assertEqual((waiting.ready, waiting.missing), (False, ['rack']))
        self.assertIsNone(self.device().name)
        self.assertEqual(self.device(rack=self.jk8).name, 'SW001')
        self.switches.required_values = []
        self.switches.save()
        self.assertEqual(self.device().name, 'SW002')

    def test_filters_for_the_whole_name(self):
        self.switches.template = '{site.name} SW-{n}{rack.name|before:-|optional}'
        self.switches.name_filters = 'ascii|nospace|lower'
        self.switches.save()
        self.assertEqual(self.device(rack=self.jk8).name, 'tamperesw-001-jk8')
        self.assertEqual(self.device().name, 'tamperesw-002')
        self.switches.template = '{site.name} SW-{n}-{rack.name}'
        self.switches.save()
        self.assertEqual(suggest(self.device(save=False)).pattern, 'tamperesw-###-<rack>')

    def test_whole_name_filters_are_checked(self):
        self.switches.name_filters = 'lower|first:3'
        with self.assertRaises(ValidationError) as caught:
            self.switches.full_clean()
        self.assertIn('name_filters', caught.exception.message_dict)

    def test_suggestion_has_a_readable_pattern(self):
        self.assertEqual(suggest(self.device(rack=self.jk8, save=False)).pattern, 'FITASWI###_JK8')
        self.assertEqual(suggest(self.device(save=False)).pattern, 'FITASWI###_<rack>')

    def test_drifted_device_gets_its_earlier_number_back(self):
        device = self.device(rack=self.jk8)
        self.device(rack=self.jk8)  # FITASWI002_JK8
        device.name = 'FITTSWI001'
        device.save()
        self.assertEqual(suggest(device).name, 'FITASWI001_JK8')
        # Once someone else has 001, the device gets the next free number.
        Device.objects.filter(name='FITASWI002_JK8').update(name='FITASWI001_JK9')
        self.assertEqual(suggest(device).name, 'FITASWI003_JK8')

    def test_suggestions_for_several_devices_are_distinct(self):
        first, second = self.device(rack=self.jk8, save=False), self.device(rack=self.jk9, save=False)
        taken = {}
        one = suggest(first, taken=taken)
        taken.setdefault(one.series, set()).add(one.number)
        self.assertEqual((one.name, suggest(second, taken=taken).name), ('FITASWI001_JK8', 'FITASWI002_JK9'))

    def test_child_role_matches(self):
        # The rule is for Switch; Access (its child) matches. A device with
        # role Switch itself matches too, but its role has no parent, so the
        # name waits for the value {role.parent.name} needs.
        device = self.device(role=self.switch, rack=self.jk8)
        self.assertIsNone(device.name)
        self.assertEqual(suggest(device).missing, ['role.parent'])

    def test_other_site_is_not_named(self):
        self.assertIsNone(self.device(site=self.helsinki).name)

    def test_existing_names_count(self):
        Device.objects.create(name='fitaswi153_old', site=self.tampere, role=self.access, device_type=self.c9300)
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI154_JK8')

    def test_longer_number_is_not_another_series(self):
        Device.objects.create(name='FITASWI1540', site=self.helsinki, role=self.router, device_type=self.c9300)
        Device.objects.create(name='FITASWIX9', site=self.helsinki, role=self.router, device_type=self.c9300)
        self.switches.number_last = 9999
        self.switches.save()
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI1541_JK8')

    def test_deleted_number_does_not_come_back(self):
        self.device(rack=self.jk8)
        second = self.device(rack=self.jk8)
        second.delete()
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI003_JK8')
        self.assertEqual(NamingSeries.objects.get(key='fitaswi').high_water, 3)

    def test_fill_gaps(self):
        self.switches.fill_gaps = True
        self.switches.save()
        self.device(rack=self.jk8)
        second = self.device(rack=self.jk8)
        self.device(rack=self.jk8)
        second.delete()
        self.assertEqual(self.device(rack=self.jk9).name, 'FITASWI002_JK9')

    def test_whole_name_scope(self):
        self.switches.number_scope = NumberScopeChoices.NAME
        self.switches.save()
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI001_JK8')
        self.assertEqual(self.device(rack=self.jk9).name, 'FITASWI001_JK9')
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI002_JK8')

    def test_digits_range_and_skip(self):
        self.switches.number_digits = 4
        self.switches.number_first = 10
        self.switches.skip_numbers = '10-11'
        self.switches.save()
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI0012_JK8')

    def test_full_series_refuses(self):
        self.switches.number_last = 1
        self.switches.save()
        self.device(rack=self.jk8)
        with self.assertRaises(ValidationError) as caught:
            self.device(rack=self.jk8)
        self.assertIn('full', str(caught.exception))

    def test_fixed_text_and_optional_rack(self):
        self.switches.template = 'FITASWI{n}{rack.name|before:_|optional}'
        self.switches.save()
        self.assertEqual(self.device().name, 'FITASWI001')
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI002_JK8')

    def test_waits_for_missing_value(self):
        device = self.device()
        self.assertIsNone(device.name)
        self.assertEqual(suggest(device).missing, ['rack'])

    def test_waiting_refused_when_enforced(self):
        self.switches.enforcement = EnforcementChoices.REFUSE
        self.switches.save()
        with self.assertRaises(ValidationError):
            self.device()

    def test_typed_name_is_kept(self):
        self.assertEqual(self.device(name='my-switch', rack=self.jk8).name, 'my-switch')

    def test_typed_name_in_series_is_remembered(self):
        self.device(name='FITASWI050_JK8', rack=self.jk8).delete()
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI051_JK8')

    def test_typed_name_above_the_range_is_not_remembered(self):
        # Too big for the high-water column, and not the rule's to hand out.
        self.device(name='FITASWI99999999999_JK8', rack=self.jk8)
        self.assertFalse(NamingSeries.objects.filter(key='fitaswi', high_water__gt=0).exists())
        self.assertEqual(self.device(rack=self.jk8).name, 'FITASWI001_JK8')

    def test_number_taken_between_validation_and_save_is_refused(self):
        self.switches.number_last = 1
        self.switches.save()
        device = self.device(rack=self.jk8, save=False)
        device.full_clean()
        self.assertEqual(device.name, 'FITASWI001_JK8')
        self.device(name='FITASWI001_JK9', rack=self.jk9)  # takes the last number meanwhile
        with self.assertRaises(AbortRequest):
            device.save()

    def test_refuse_enforcement(self):
        self.switches.enforcement = EnforcementChoices.REFUSE
        self.switches.save()
        with self.assertRaises(ValidationError):
            self.device(name='my-switch', rack=self.jk8)
        with self.assertRaises(ValidationError):
            self.device(name='FITASWI005_JK9', rack=self.jk8)  # wrong rack part
        self.assertEqual(self.device(name='FITASWI005_JK8', rack=self.jk8).name, 'FITASWI005_JK8')
        with self.assertRaises(ValidationError) as caught:
            self.device(name='FITASWI005_JK9', rack=self.jk9)  # number already used
        self.assertIn('already used', str(caught.exception))

    def test_warn_allows_any_name(self):
        self.assertEqual(self.device(name='whatever', rack=self.jk8).name, 'whatever')

    def test_edit_never_renames(self):
        device = self.device(rack=self.jk8)
        device.rack = self.jk9
        device.full_clean()
        device.save()
        device.refresh_from_db()
        self.assertEqual(device.name, 'FITASWI001_JK8')
        # The suggestion keeps the device's number in its series.
        result = suggest(device)
        self.assertEqual((result.name, result.kept_number), ('FITASWI001_JK9', True))

    def test_legacy_name_not_refused_on_other_edits(self):
        device = Device.objects.create(name='legacy', site=self.tampere, role=self.access, device_type=self.c9300,
                                       rack=self.jk8)
        self.switches.enforcement = EnforcementChoices.REFUSE
        self.switches.save()
        device.serial = 'X1'
        device.full_clean()
        device.save()
        device.name = 'still-legacy'
        with self.assertRaises(ValidationError):
            device.full_clean()

    def test_priority_and_tags(self):
        ot = self.rule(roles=[self.router], sites=[self.tampere], match_tags=[self.ot], priority=10,
                       template='FITAROT{n}', name='OT routers')
        self.rule(roles=[self.router], sites=[self.tampere], priority=100, template='FITARO{n}', name='Routers')
        self.assertEqual(self.device(role=self.router, tags=[self.ot]).name, 'FITAROT001')
        self.assertEqual(self.device(role=self.router).name, 'FITARO001')
        ot.tag_match = 'any'
        ot.save()
        self.assertEqual(self.device(role=self.router, tags=[self.ot]).name, 'FITAROT002')

    def test_disabled_rule(self):
        self.switches.enabled = False
        self.switches.save()
        self.assertIsNone(self.device(rack=self.jk8).name)

    def test_advanced_condition(self):
        self.switches.constraint = {'serial__startswith': 'FOC'}
        self.switches.save()
        self.assertIsNone(self.device(rack=self.jk8, serial='ABC').name)
        self.assertEqual(self.device(rack=self.jk8, serial='FOC1').name, 'FITASWI001_JK8')

    def test_advanced_condition_cannot_read_users(self):
        secret = {'journal_entries__created_by__password__startswith': 'pbkdf2'}
        for constraint in (secret, {'nonsense__exact': 1}):
            self.switches.constraint = constraint
            with self.assertRaises(ValidationError) as caught:
                self.switches.full_clean()
            self.assertIn('constraint', caught.exception.message_dict)
        # A rule saved with it anyway (through the database) never matches.
        NamingRule.objects.filter(pk=self.switches.pk).update(constraint=secret)
        self.assertIsNone(self.device(rack=self.jk8).name)

    def test_rule_needs_valid_template(self):
        self.switches.template = '{site}'
        with self.assertRaises(ValidationError):
            self.switches.full_clean()

    def test_save_without_validation_is_named_too(self):
        device = Device(site=self.tampere, role=self.access, device_type=self.c9300, rack=self.jk8)
        device.save()
        self.assertEqual(device.name, 'FITASWI001_JK8')


class NumberFromIPTests(NetBoxData, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.make_netbox()
        cls.rule(roles=[cls.switch], template='fitaswi{n}', number_source=NumberSourceChoices.IP,
                 ip_pattern='*.*.*.N')

    def add_primary(self, device, address):
        interface = Interface.objects.create(device=device, name='vlan10', type=InterfaceTypeChoices.TYPE_VIRTUAL)
        ip = IPAddress.objects.create(address=address, assigned_object=interface)
        device.primary_ip4 = ip
        device.full_clean()
        device.save()
        return device

    def test_named_once_it_has_a_primary_ip(self):
        device = self.device()
        self.assertIsNone(device.name)
        self.add_primary(device, '192.168.10.6/24')
        device.refresh_from_db()
        self.assertEqual(device.name, 'fitaswi006')

    def test_named_when_netbox_sets_primary_ip_without_validating(self):
        device = self.device()
        interface = Interface.objects.create(device=device, name='vlan10', type=InterfaceTypeChoices.TYPE_VIRTUAL)
        device.primary_ip4 = IPAddress.objects.create(address='192.168.10.7/24', assigned_object=interface)
        device.save()
        device.refresh_from_db()
        self.assertEqual(device.name, 'fitaswi007')

    def test_same_number_twice_is_refused(self):
        self.add_primary(self.device(), '192.168.10.6/24')
        other = self.device()
        with self.assertRaises(ValidationError):
            self.add_primary(other, '10.0.0.6/24')


class ConcurrencyTests(NetBoxData, TransactionTestCase):
    """Two devices saved at the same time get different numbers."""

    def setUp(self):
        self.make_netbox()
        self.rule(roles=[self.switch], template='FITASWI{n}')

    def test_parallel_saves(self):
        names = []
        errors = []
        barrier = threading.Barrier(2)

        def create():
            try:
                barrier.wait()
                with transaction.atomic():
                    device = self.device(save=False)
                    device.full_clean()
                    device.save()
                    names.append(device.name)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=create) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(names), ['FITASWI001', 'FITASWI002'])
