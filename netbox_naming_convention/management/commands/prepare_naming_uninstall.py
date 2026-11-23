"""
Remove what would break NetBox pages once this plugin is gone. Run it while
the plugin is still installed, right before taking it out of PLUGINS.

The plugin never changes NetBox's own tables, but NetBox keeps rows about
any object, naming rules included: change log and journal entries,
bookmarks, notifications, tag assignments and the like. Once the plugin's
models are gone, a page listing such a row can't load the object behind it
and fails with a server error.

So this deletes those rows, and takes the plugin's object types off custom
fields, custom links, export templates, saved filters, tags, event rules and
permissions (deleting the ones that were only about this plugin), and
deletes custom fields whose values are this plugin's objects.

Devices, virtual machines and racks keep the names the rules gave them. The
plugin's own tables are left alone; `migrate netbox_naming_convention zero`
removes those.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from core.models import Job, ObjectChange
from extras.models import (
    Bookmark, CachedValue, CustomField, CustomLink, EventRule, ExportTemplate, ImageAttachment, JournalEntry,
    Notification, SavedFilter, Subscription, TableConfig, Tag, TaggedItem,
)
from users.models import ObjectPermission

APP_LABEL = 'netbox_naming_convention'


def _rows():
    """Rows in NetBox's own tables that point at this plugin's objects."""
    ours = {'object_type__app_label': APP_LABEL}
    return {
        'notifications': Notification.objects.filter(**ours),
        'bookmarks': Bookmark.objects.filter(**ours),
        'subscriptions': Subscription.objects.filter(**ours),
        'changelog entries': ObjectChange.objects.filter(
            Q(changed_object_type__app_label=APP_LABEL) | Q(related_object_type__app_label=APP_LABEL)
        ),
        'journal entries': JournalEntry.objects.filter(assigned_object_type__app_label=APP_LABEL),
        'tag assignments': TaggedItem.objects.filter(content_type__app_label=APP_LABEL),
        'image attachments': ImageAttachment.objects.filter(**ours),
        'saved table configs': TableConfig.objects.filter(**ours),
        'search index entries': CachedValue.objects.filter(**ours),
        'background jobs': Job.objects.filter(**ours),
    }


def _object_type_users():
    """
    NetBox objects limited to object types, offered on any of this plugin's.
    Each gets this plugin's types removed; the ones left with no object type
    at all were only about this plugin and are deleted.
    """
    found = {}
    for label, model in (
        ('custom fields', CustomField), ('custom links', CustomLink), ('export templates', ExportTemplate),
        ('saved filters', SavedFilter), ('tags', Tag), ('event rules', EventRule), ('permissions', ObjectPermission),
    ):
        objects = list(model.objects.filter(object_types__app_label=APP_LABEL).distinct())
        if objects:
            found[label] = objects
    return found


def _only_ours(obj):
    return not obj.object_types.exclude(app_label=APP_LABEL).exists()


class Command(BaseCommand):
    help = (
        "Delete NetBox rows that point at this plugin's objects (changelog and journal entries, bookmarks, "
        'notifications, tag assignments, ...) and take its object types off custom fields, tags, event rules, '
        'permissions and the like, so NetBox keeps working after the plugin is removed.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only show what would be removed.')
        parser.add_argument('--noinput', '--no-input', action='store_false', dest='interactive',
                            help='Do not ask for confirmation.')

    def handle(self, *args, dry_run=False, interactive=True, **options):
        rows = _rows()
        users = _object_type_users()
        object_fields = list(CustomField.objects.filter(related_object_type__app_label=APP_LABEL))

        for name, queryset in rows.items():
            if count := queryset.count():
                self.stdout.write(f'{count} {name} for naming objects')
        for label, objects in users.items():
            deleted = [str(obj) for obj in objects if _only_ours(obj)]
            kept = [str(obj) for obj in objects if not _only_ours(obj)]
            if kept:
                self.stdout.write(f'{label} to take naming object types off: {", ".join(kept)}')
            if deleted:
                self.stdout.write(f'{label} only for naming objects, to delete: {", ".join(deleted)}')
        if object_fields:
            names = ', '.join(str(field) for field in object_fields)
            self.stdout.write(f'custom fields pointing at naming objects, to delete: {names}')

        if dry_run:
            return
        if interactive and input('Remove these? [y/N] ').strip().lower() not in ('y', 'yes'):
            self.stdout.write('Nothing removed.')
            return

        with transaction.atomic():
            for queryset in rows.values():
                queryset.delete()
            for objects in users.values():
                for obj in objects:
                    if _only_ours(obj):
                        obj.delete()
                    else:
                        obj.object_types.remove(*obj.object_types.filter(app_label=APP_LABEL))
            for field in object_fields:
                field.delete()
        self.stdout.write(self.style.SUCCESS(
            'Done. Run `manage.py migrate netbox_naming_convention zero`, then take netbox_naming_convention '
            'out of PLUGINS and restart NetBox.'
        ))
