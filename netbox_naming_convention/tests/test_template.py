"""Templates and numbers, without the database."""
from django.test import SimpleTestCase

from ..numbering import NumberError, next_number, number_from_ip, parse_skip
from ..template import Template, TemplateError

VALUES = {
    ('site', 'name'): 'Utrecht',
    ('role', 'name'): 'Access',
    ('role', 'parent', 'name'): 'Switch',
    ('rack', 'name'): 'RA8',
    ('site', 'cf', 'code'): 'UT',
    ('location', 'name'): '',
}


def render(text, values=VALUES):
    return Template(text).render(lambda path: values.get(tuple(path), ''))


class TemplateTests(SimpleTestCase):
    def test_example_from_the_plan(self):
        out = render('NL{site.name|first:2|upper}{role.parent.name|first:3|upper}{n}_{rack.name}')
        self.assertEqual((out.prefix, out.suffix, out.missing), ('NLUTSWI', '_RA8', []))
        self.assertEqual(out.name('154'), 'NLUTSWI154_RA8')

    def test_fixed_text(self):
        out = render('NLUTSWI{n}')
        self.assertEqual((out.prefix, out.suffix), ('NLUTSWI', ''))

    def test_no_number(self):
        out = render('{site.name|lower}-{rack.name}')
        self.assertFalse(out.has_number)
        self.assertEqual(out.name(), 'utrecht-RA8')

    def test_missing_value_waits(self):
        out = render('NLUT{n}{location.name}')
        self.assertEqual(out.missing, ['location'])

    def test_optional_and_before(self):
        out = render('NLUT{n}{location.name|before:_|optional}{rack.name|before:_}')
        self.assertEqual((out.suffix, out.missing), ('_RA8', []))

    def test_default(self):
        self.assertEqual(render('{location.name|default:X}').prefix, 'X')

    def test_filters(self):
        values = {('site', 'name'): 'Hämeen Linna'}
        self.assertEqual(render('{site.name|ascii|nospace|upper}', values).prefix, 'HAMEENLINNA')
        self.assertEqual(render('{site.name|last:5}', values).prefix, 'Linna')
        self.assertEqual(render('{site.name|replace: :-}', values).prefix, 'Hämeen-Linna')
        self.assertEqual(render('{site.name|replace: }', values).prefix, 'HämeenLinna')

    def test_custom_field(self):
        self.assertEqual(render('NL{site.cf.code}').prefix, 'NLUT')

    def test_literal_braces(self):
        self.assertEqual(render('a{{b}}').prefix, 'a{b}')

    def test_errors(self):
        for bad in ('{n}{n}', '{site}', '{site.password}', '{nothing.name}', '{site.name|shout}', 'a{', 'a}',
                    '{site.name|first:x}', '{}', '{role.parent}', '{device.comments}'):
            with self.subTest(bad), self.assertRaises(TemplateError):
                Template(bad)


class NumberTests(SimpleTestCase):
    def test_next_after_highest(self):
        self.assertEqual(next_number({1, 2, 5}, first=1, last=999), 6)

    def test_high_water_keeps_deleted_numbers_away(self):
        self.assertEqual(next_number({1, 2}, first=1, last=999, high_water=5), 6)

    def test_fill_gaps(self):
        self.assertEqual(next_number({1, 2, 5}, first=1, last=999, fill_gaps=True, high_water=5), 3)

    def test_released_numbers_come_back_first(self):
        # 3 was never approved; 4 is skipped; 2 is in use again.
        released = [2, 3, 4]
        self.assertEqual(next_number({1, 2, 5}, first=1, last=999, skip=parse_skip('4'), high_water=5,
                                     released=released), 3)
        self.assertEqual(next_number({1, 2, 3, 5}, first=1, last=999, high_water=5, released=[2, 3]), 6)

    def test_first_number(self):
        self.assertEqual(next_number(set(), first=100, last=999), 100)

    def test_skip(self):
        skip = parse_skip('0, 3-4')
        self.assertEqual(next_number({1, 2}, first=0, last=999, skip=skip, fill_gaps=True), 5)
        self.assertEqual(next_number({1, 2}, first=1, last=999, skip=skip), 5)

    def test_large_skipped_range_is_jumped_over(self):
        skip = parse_skip('1-999999990, 999999992')
        for fill_gaps in (False, True):
            self.assertEqual(next_number(set(), first=1, last=999999999, skip=skip, fill_gaps=fill_gaps), 999999991)
        self.assertEqual(next_number({999999991}, first=1, last=999999999, skip=skip, fill_gaps=True), 999999993)

    def test_number_above_the_range_does_not_fill_the_series(self):
        self.assertEqual(next_number({1, 5000}, first=1, last=999), 2)

    def test_full(self):
        with self.assertRaises(NumberError):
            next_number({1, 2, 3}, first=1, last=3)
        with self.assertRaises(NumberError):
            next_number({1, 3}, first=1, last=3, high_water=3)

    def test_bad_skip(self):
        for bad in ('x', '5-3', '-1'):
            with self.subTest(bad), self.assertRaises(NumberError):
                parse_skip(bad)

    def test_ip_mask(self):
        self.assertEqual(number_from_ip('*.*.*.N', '10.20.30.6/24'), 6)
        self.assertEqual(number_from_ip('10.*.N.*', '10.1.20.3'), 20)
        self.assertIsNone(number_from_ip('10.*.N.*', '192.168.1.1'))

    def test_ip_regex(self):
        self.assertEqual(number_from_ip(r'\.(\d+)$', '10.20.30.154/24'), 154)
        self.assertEqual(number_from_ip(r'::(?P<n>\d+)$', '2001:db8::42/64'), 42)

    def test_bad_ip_pattern(self):
        for bad in ('*.*.N.N', '(', 'abc'):
            with self.subTest(bad), self.assertRaises(NumberError):
                number_from_ip(bad, '10.0.0.1')
