"""
The naming report: how the names of one kind of object (devices, virtual
machines or racks) stand against the rules.

Every object the user may see is put in one group:

- *follows*: its name fits the rule that names it;
- *drifted*: it has a name that doesn't fit its rule;
- *unnamed*: a rule names it, but it has no name (devices made before the rule);
- *no_rule*: no enabled rule names it.

The report reads only; renaming goes through the rename page like on a rule.
"""
from dataclasses import dataclass, field

from .matching import find_rule, ordered_rules, rules_queryset
from .naming import follows, suggest

#: Most objects the report looks at.
REPORT_LIMIT = 5000
#: Most objects of a group listed (with a suggested name).
REPORT_SHOWN = 100

GROUPS = ('drifted', 'unnamed', 'no_rule', 'follows')


@dataclass
class RuleCount:
    rule: object
    count: int = 0
    drifted: int = 0


@dataclass
class Report:
    kind: object
    counts: dict = field(default_factory=lambda: dict.fromkeys(GROUPS, 0))
    rules: list = field(default_factory=list)
    #: The objects of the group asked for, at most REPORT_SHOWN.
    shown: list = field(default_factory=list)
    truncated: bool = False

    @property
    def total(self):
        return sum(self.counts.values())


def related_fields(kind):
    """What to select_related for naming objects of `kind` without a query per object."""
    related = ['__'.join(root) for root in kind.roots.values() if root]
    if kind.has_primary_ip:
        related += ['primary_ip4', 'primary_ip6']
    return related


def group_of(obj, rules):
    """(group, rule) for one object; `rules` are the kind's rules in order."""
    rule = find_rule(obj, rules, tag_slugs={tag.slug for tag in obj.tags.all()})
    if rule is None:
        return 'no_rule', None
    if not obj.name:
        return 'unnamed', rule
    _rule, fits = follows(obj, rule)
    return ('follows' if fits else 'drifted'), rule


def build_report(kind, objects, show='drifted'):
    """The report for `objects` (a queryset of `kind`), listing the group `show`."""
    report = Report(kind)
    rules = ordered_rules(rules_queryset(kind))
    per_rule = {rule.pk: RuleCount(rule) for rule in rules}
    objects = objects.select_related(*related_fields(kind)).prefetch_related('tags').order_by('name', 'pk')
    taken = {}
    seen = 0
    for obj in objects.iterator(chunk_size=500):
        if seen >= REPORT_LIMIT:
            report.truncated = True
            break
        seen += 1
        group, rule = group_of(obj, rules)
        report.counts[group] += 1
        if rule is not None:
            per_rule[rule.pk].count += 1
            per_rule[rule.pk].drifted += group in ('drifted', 'unnamed')
        if group != show or len(report.shown) >= REPORT_SHOWN:
            continue
        obj.naming_rule = rule
        obj.suggested_name = None
        if rule is not None:
            # Numbers suggested earlier on the page count as taken, as when renaming.
            hint = suggest(obj, rule, taken=taken)
            if hint.ready:
                obj.suggested_name = hint.name
                if hint.number is not None:
                    taken.setdefault(hint.series, set()).add(hint.number)
        report.shown.append(obj)
    report.rules = [entry for entry in per_rule.values() if entry.count]
    return report
