# apps/ofertas/management/commands/sync_ofertas_addinteli.py

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from apps.ofertas.utils.sync_addinteli import sync_addinteli_offers

class Command(BaseCommand):
    help = _("Synchronizes offers from Addinteli API (or mock data)")

    def handle(self, *args, **options):
        try:
            new_count, updated_count = sync_addinteli_offers()
            self.stdout.write(
                self.style.SUCCESS(
                    _(f"Synchronization successful: {new_count} new offers created, {updated_count} updated")
                )
            )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(
                    _(f"Failed to synchronize offers: {str(e)}")
                )
            )
            raise