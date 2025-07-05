"""
integraciones.apis.management.commands.sync_planes_addinteli
----------------------------------------------------------
Django management command to synchronize plans from Addinteli API to local database.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.cache import cache
from django.conf import settings
from integraciones.apis.base import AddinteliAPIClient
from integraciones.apis.constants import ENDPOINTS
from apps.ofertas.models import Oferta  # Assumes Oferta model exists

class Command(BaseCommand):
    """Synchronize plans from Addinteli API to local database."""
    help = "Sync available plans from Addinteli API"

    def add_arguments(self, parser):
        """Add command-line arguments."""
        parser.add_argument(
            "--sandbox",
            action="store_true",
            help="Use sandbox API mode instead of production",
        )

    def handle(self, *args, **options):
        """Execute the plan synchronization."""
        client = AddinteliAPIClient()
        api_mode = "sandbox" if options["sandbox"] else settings.ADDINTELI_API_MODE
        base_url = settings.ADDINTELI_API_URL[api_mode]
        
        try:
            with transaction.atomic():
                plans = []
                payload = {
                    "distributor_id": settings.ADDINTELI_DISTRIBUTOR_ID,
                    "wallet_id": settings.ADDINTELI_WALLET_ID,
                }
                next_url = f"{base_url}{ENDPOINTS['PLANES_DISPONIBLES']}"
                
                while next_url:
                    response = client.post(next_url, payload)
                    plans.extend(response.get("result", []))
                    next_url = response.get("next_url", None)
                
                for plan in plans:
                    Oferta.objects.update_or_create(
                        plan_name=plan["plan_name"],
                        defaults={
                            "client_cost": plan["client_price"],  # Maps to Excel naming
                            "eu_price": plan["eu_price"],
                            "plan_description": plan["plan_description"],
                            "omv_name": plan["omv_name"],
                            "validity_type": plan["validity_type"],
                            "validity": plan["validity"],
                            "product_type": plan["product_type"],
                            "data_mb": plan["data_mb"],
                            "min": plan["min"],
                            "sms": plan["sms"],
                            "social_networks": plan["social_networks"],
                        }
                    )
                
                # Clear cache
                cache.delete_pattern("ofertas_*")
                self.stdout.write(self.style.SUCCESS(f"Successfully synchronized {len(plans)} plans"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to sync plans: {str(e)}"))
            raise