# apps/ofertas/services.py

import logging
from typing import List, Dict
from decimal import Decimal
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from .models import Oferta, MargenDistribuidor, ListaPreciosEspecial, OfertaListaPreciosEspecial, ClienteListaAsignada

# Configure logging
logger = logging.getLogger(__name__)

# Load constants (moved to constants.py for modularity, included here temporarily)
from .models import CURRENCY_CHOICES

class AddinteliClient:
    """Enterprise-grade client for Addinteli API with retry logic and mocking support."""
    def __init__(self):
        self.base_url = settings.ADDINTELI_API_URL  # e.g., 'http://localhost:8000/mock/' or production URL
        self.distributor_id = settings.ADDINTELI_DISTRIBUTOR_ID
        self.wallet_id = settings.ADDINTELI_WALLET_ID
        self.api_key = settings.ADDINTELI_API_KEY
        self.timeout = 10  # seconds
        self.session = self._create_session()

    def _create_session(self):
        """Configure session with retry strategy for robustness."""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def fetch_offers(self) -> List[dict]:
        """Fetch offers from Addinteli API with caching and error handling."""
        cache_key = 'addinteli_ofertas_catalog_current'
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.info("Offers retrieved from cache")
            return cached_data

        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            }
            response = self.session.get(
                f'{self.base_url}/getplans',
                headers=headers,
                timeout=self.timeout,
                params={'distributor_id': self.distributor_id, 'wallet_id': self.wallet_id}
            )
            response.raise_for_status()
            try:
                data = response.json()
                offers = data.get('result', [])
                if not isinstance(offers, list):
                    raise ValueError("Invalid offers format in response")
            except ValueError as e:
                logger.error(f"Invalid JSON response from Addinteli: {str(e)}")
                offers = []
            cache.set(cache_key, offers, CACHE_TIMEOUT)
            logger.info(f"Successfully fetched {len(offers)} offers from Addinteli")
            return offers
        except requests.RequestException as e:
            logger.error(f"Failed to fetch offers from Addinteli: {str(e)}")
            # Mock data for development with sanitization
            return [
                {
                    'codigo_addinteli': 'PLAN_TEST_5GB',
                    'nombre': 'Plan Test 5GB',
                    'descripcion': '5GB - Test Plan',
                    'costo_base': str(100.00),
                    'duracion_dias': 30
                }
            ]

def synchronize_offers() -> int:
    """Synchronize offers from Addinteli and update local database with optimization."""
    client = AddinteliClient()
    offers_data = client.fetch_offers()
    updated_count = 0

    with transaction.atomic():
        for i in range(0, len(offers_data), BATCH_SIZE):
            batch = offers_data[i:i + BATCH_SIZE]
            for offer_data in batch:
                oferta, created = Oferta.objects.update_or_create(
                    codigo_addinteli=offer_data['codigo_addinteli'],
                    defaults={
                        'nombre': offer_data['nombre'],
                        'descripcion': offer_data.get('descripcion'),
                        'costo_base': Decimal(str(offer_data['costo_base'])).quantize(Decimal('0.01')),
                        'duracion_dias': offer_data.get('duracion_dias', 30),
                        'moneda': 'MXN',
                        'activo': True,
                        'fecha_sincronizacion': timezone.now(),
                    }
                )
                if created:
                    logger.info(f"Created new offer: {oferta}")
                else:
                    logger.info(f"Updated offer: {oferta}")
                updated_count += 1

        # Deactivate obsolete offers
        active_codes = set(o['codigo_addinteli'] for o in offers_data)
        Oferta.objects.exclude(codigo_addinteli__in=active_codes).update(activo=False)
        logger.info(f"Deactivated {Oferta.objects.filter(activo=False).count()} obsolete offers")

        # Invalidate cache
        cache.delete('addinteli_ofertas_catalog_current')
        logger.info("Cache invalidated after synchronization")

    return updated_count

def validate_margins(margen: MargenDistribuidor) -> None:
    """Validate price coherence and margins with strict business rules."""
    if margen.precio_vendedor < margen.precio_distribuidor:
        raise ValidationError("El precio vendedor no puede ser menor al precio distribuidor.")
    if margen.precio_cliente < margen.precio_vendedor:
        raise ValidationError("El precio cliente no puede ser menor al precio vendedor.")
    total_margin = margen.margen_total
    if total_margin < Decimal('0.00'):
        raise ValidationError("El margen total no puede ser negativo.")
    logger.info(f"Márgenes validados para oferta {margen.oferta}: Total = {total_margin}")

def get_applicable_price(oferta: Oferta, user) -> Decimal:
    """Calculate the applicable price based on user role and VIP status."""
    try:
        cliente_lista = ClienteListaAsignada.objects.select_related('lista').get(cliente=user)
        precio_especial_obj = OfertaListaPreciosEspecial.objects.select_related('lista', 'oferta').get(
            lista=cliente_lista.lista, oferta=oferta
        )
        if precio_especial_obj.precio_cliente_especial < oferta.costo_base:
            raise ValidationError("Precio especial no puede ser menor al costo base.")
        logger.info(f"Applied special price {precio_especial_obj.precio_cliente_especial} for VIP user {user}")
        return precio_especial_obj.precio_cliente_especial
    except (ClienteListaAsignada.DoesNotExist, OfertaListaPreciosEspecial.DoesNotExist):
        pass

    distribuidor = getattr(user, 'distribuidor', user if hasattr(user, 'rol') and user.rol == 'distribuidor' else None)
    if not distribuidor:
        raise ValidationError("No se pudo determinar el distribuidor para el usuario.")
    try:
        margen = MargenDistribuidor.objects.select_related('oferta').get(oferta=oferta, distribuidor=distribuidor)
        validate_margins(margen)
        logger.info(f"Applied standard price {margen.precio_cliente} for user {user}")
        return margen.precio_cliente
    except MargenDistribuidor.DoesNotExist:
        raise ValidationError(f"No existe margen asignado para la oferta {oferta} y distribuidor {distribuidor}.")

def prepare_activation_data(oferta: Oferta, user) -> Dict[str, Decimal]:
    """Prepare comprehensive financial data package for activation/recharge modules."""
    price = get_applicable_price(oferta, user)

    with transaction.atomic():
        distribuidor = getattr(user, 'distribuidor', user if hasattr(user, 'rol') and user.rol == 'distribuidor' else None)
        if not distribuidor:
            raise ValidationError("No se pudo determinar el distribuidor.")
        margen = MargenDistribuidor.objects.select_for_update().select_related('oferta').get(oferta=oferta, distribuidor=distribuidor)
        validate_margins(margen)

        return {
            'codigo_addinteli': oferta.codigo_addinteli,
            'precio_cobrado': price,
            'comision_admin': margen.margen_admin,
            'comision_distribuidor': margen.margen_distribuidor,
            'comision_vendedor': margen.margen_vendedor,
            'margen_total': margen.margen_total,
            'duracion_dias': oferta.duracion_dias,
            'moneda': oferta.moneda,
        }