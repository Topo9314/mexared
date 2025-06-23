# apps/ofertas/utils/sync_addinteli.py

import logging
from typing import List, Dict, Tuple
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.core.cache import cache
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from apps.ofertas.models import Oferta

logger = logging.getLogger(__name__)

# Constants for configuration
BATCH_SIZE = 100  # Number of offers to process per batch
CACHE_TIMEOUT = 3600  # Cache duration in seconds (1 hour)
ADDINTELI_API_TIMEOUT = 10  # API request timeout in seconds

class AddinteliSyncClient:
    """Client for synchronizing offers from Addinteli API with retry and mock support."""
    
    def __init__(self):
        self.base_url = getattr(settings, 'ADDINTELI_API_URL', 'https://api.addinteli.com')
        self.api_key = getattr(settings, 'ADDINTELI_API_KEY', '')
        self.distributor_id = getattr(settings, 'ADDINTELI_DISTRIBUTOR_ID', '')
        self.wallet_id = getattr(settings, 'ADDINTELI_WALLET_ID', '')
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a session with retry strategy for robust API calls."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_mock_data(self) -> List[Dict]:
        """Return mock data for testing when API is not available."""
        return [
            {
                "codigo_addinteli": "MOV-001",
                "nombre": "Paquete Móvil Básico",
                "descripcion": "Plan de llamadas y SMS",
                "costo_base": "100.00",
                "duracion_dias": 30,
                "categoria_servicio": "movilidad",
                "moneda": "MXN",
                "language": "es"
            },
            {
                "codigo_addinteli": "MIFI-002",
                "nombre": "Plan MIFI Avanzado",
                "descripcion": "Internet 150 GB",
                "costo_base": "250.00",
                "duracion_dias": 30,
                "categoria_servicio": "mifi",
                "moneda": "MXN",
                "language": "es"
            },
            {
                "codigo_addinteli": "HBB-003",
                "nombre": "Hogar Conectado",
                "descripcion": "Internet residencial 50 Mbps",
                "costo_base": "400.00",
                "duracion_dias": 30,
                "categoria_servicio": "hbb",
                "moneda": "MXN",
                "language": "es"
            }
        ]

    def fetch_offers(self) -> List[Dict]:
        """Fetch offers from Addinteli API or return mock data if API is unavailable."""
        cache_key = 'addinteli_ofertas_catalog_current'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info("Retrieved offers from cache")
            return cached_data

        # Check if API is enabled (based on settings)
        if not self.api_key or self.base_url == 'mock':
            logger.warning("API key missing or mock mode enabled. Using mock data.")
            mock_data = self._get_mock_data()
            cache.set(cache_key, mock_data, CACHE_TIMEOUT)
            return mock_data

        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            response = self.session.get(
                f'{self.base_url}/getplans',
                headers=headers,
                timeout=ADDINTELI_API_TIMEOUT,
                params={
                    'distributor_id': self.distributor_id,
                    'wallet_id': self.wallet_id
                }
            )
            response.raise_for_status()
            data = response.json()
            offers = data.get('result', [])
            if not isinstance(offers, list):
                raise ValueError("Invalid offers format in API response")

            logger.info(f"Fetched {len(offers)} offers from Addinteli API")
            cache.set(cache_key, offers, CACHE_TIMEOUT)
            return offers

        except requests.RequestException as e:
            logger.error(f"Failed to fetch offers from Addinteli API: {str(e)}")
            logger.warning("Falling back to mock data due to API failure")
            mock_data = self._get_mock_data()
            cache.set(cache_key, mock_data, CACHE_TIMEOUT)
            return mock_data
        except ValueError as e:
            logger.error(f"Invalid API response format: {str(e)}")
            logger.warning("Falling back to mock data due to invalid response")
            mock_data = self._get_mock_data()
            cache.set(cache_key, mock_data, CACHE_TIMEOUT)
            return mock_data

def sync_addinteli_offers() -> Tuple[int, int]:
    """
    Synchronize offers from Addinteli API or mock data into the Oferta model.
    
    Returns:
        Tuple[int, int]: Number of new offers created and updated.
    """
    client = AddinteliSyncClient()
    offers_data = client.fetch_offers()
    new_count = 0
    updated_count = 0

    try:
        with transaction.atomic():
            # Process offers in batches to optimize database performance
            for i in range(0, len(offers_data), BATCH_SIZE):
                batch = offers_data[i:i + BATCH_SIZE]
                for item in batch:
                    try:
                        # Validate and sanitize data
                        costo_base = Decimal(str(item.get('costo_base', '0.00'))).quantize(Decimal('0.01'))
                        if costo_base < 0:
                            logger.warning(f"Invalid costo_base for {item['codigo_addinteli']}: {costo_base}")
                            continue

                        oferta, created = Oferta.objects.update_or_create(
                            codigo_addinteli=item['codigo_addinteli'],
                            defaults={
                                'nombre': item.get('nombre', ''),
                                'descripcion': item.get('descripcion', ''),
                                'costo_base': costo_base,
                                'duracion_dias': item.get('duracion_dias', 30),
                                'categoria_servicio': item.get('categoria_servicio', 'movilidad'),
                                'moneda': item.get('moneda', 'MXN'),
                                'language': item.get('language', 'es'),
                                'activo': True,
                                'version': item.get('version', 1),
                                'fecha_sincronizacion': timezone.now(),
                            }
                        )
                        if created:
                            new_count += 1
                            logger.info(f"Created new offer: {oferta}")
                        else:
                            updated_count += 1
                            logger.info(f"Updated offer: {oferta}")

                    except (ValueError, KeyError) as e:
                        logger.error(f"Error processing offer {item.get('codigo_addinteli', 'unknown')}: {str(e)}")
                        continue

            # Deactivate obsolete offers
            active_codes = {item['codigo_addinteli'] for item in offers_data}
            deactivated = Oferta.objects.exclude(codigo_addinteli__in=active_codes).update(activo=False)
            if deactivated:
                logger.info(f"Deactivated {deactivated} obsolete offers")

            # Invalidate cache for distributor views
            cache.delete_pattern('distributor_*_offers')
            cache.delete('addinteli_ofertas_catalog_current')
            logger.info("Invalidated cache after synchronization")

        logger.info(f"✅ Synchronization complete: {new_count} new offers, {updated_count} updated")
        return new_count, updated_count

    except Exception as e:
        logger.error(f"Critical error during synchronization: {str(e)}", exc_info=True)
        raise