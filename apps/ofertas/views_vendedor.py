# apps/ofertas/views_vendedor.py

import logging
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Sum
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
import csv

from apps.ofertas.models import Oferta, MargenDistribuidor, MargenVendedor
from apps.ofertas.services import prepare_activation_data  # For future activation hooks

# Configure logging with international audit readiness
logger = logging.getLogger(__name__)

# Permission check for vendor role
def is_vendedor(user):
    return user.is_authenticated and user.rol == 'vendedor'

@login_required
@user_passes_test(is_vendedor)
def vendedor_dashboard(request):
    """
    Display the vendor's main dashboard with real-time KPIs.
    """
    vendedor = request.user
    total_ofertas = MargenVendedor.objects.filter(vendedor=vendedor, activo=True).count()
    total_ganancias = MargenVendedor.objects.filter(vendedor=vendedor, activo=True).aggregate(
        total=Sum('precio_vendedor_final')
    )['total'] or 0
    last_sync = Oferta.objects.latest('fecha_sincronizacion').fecha_sincronizacion if Oferta.objects.exists() else None

    context = {
        'total_ofertas': total_ofertas,
        'total_ganancias': total_ganancias,
        'currency': 'MXN',  # Extensible via settings
        'last_sync': last_sync,
    }
    logger.info(f"Vendor {vendedor.username} accessed dashboard at {timezone.now()} UTC")
    return render(request, 'ofertas/vendedor_dashboard.html', context)

@login_required
@user_passes_test(is_vendedor)
def lista_ofertas_asignadas(request):
    """
    List all active offers assigned to the vendor.
    """
    vendedor = request.user
    ofertas = MargenVendedor.objects.filter(vendedor=vendedor, activo=True).select_related('oferta', 'distribuidor')
    context = {
        'ofertas': ofertas,
        'currency': 'MXN',
    }
    logger.info(f"Vendor {vendedor.username} viewed assigned offers at {timezone.now()} UTC")
    return render(request, 'ofertas/vendedor_list_offers.html', context)

@login_required
@user_passes_test(is_vendedor)
def detalle_margen_oferta(request, offer_id):
    """
    Display detailed margin breakdown for a specific offer.
    """
    vendedor = request.user
    margen_vendedor = get_object_or_404(MargenVendedor, vendedor=vendedor, oferta_id=offer_id, activo=True)
    margen_distribuidor = get_object_or_404(MargenDistribuidor, distribuidor=margen_vendedor.distribuidor, oferta_id=offer_id, activo=True)

    breakdown = {
        'costo_base': margen_distribuidor.oferta.costo_base,
        'precio_distribuidor': margen_distribuidor.precio_distribuidor,
        'precio_vendedor': margen_distribuidor.precio_vendedor,
        'precio_asignado_vendedor': margen_vendedor.precio_vendedor_final,
        'precio_cliente': margen_distribuidor.precio_cliente,
        'margen_vendedor': margen_vendedor.precio_vendedor_final - margen_distribuidor.precio_distribuidor,
        'margen_total': margen_distribuidor.margen_total,
    }

    context = {
        'breakdown': breakdown,
        'currency': 'MXN',
    }
    logger.info(f"Vendor {vendedor.username} viewed margin breakdown for offer {offer_id} at {timezone.now()} UTC")
    return render(request, 'ofertas/vendedor_offer_detail.html', context)

@login_required
@user_passes_test(is_vendedor)
def exportar_ofertas_vendedor(request):
    """
    Export all assigned offers for the vendor in CSV format.
    """
    vendedor = request.user
    ofertas = MargenVendedor.objects.filter(vendedor=vendedor, activo=True).select_related('oferta', 'distribuidor')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="ofertas_vendedor_{vendedor.username}_{timezone.now().strftime("%Y%m%d_%H%M")}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Oferta', 'Precio Cliente Final', 'Asignado el', 'Distribuidor', 'Moneda'])
    
    for oferta in ofertas:
        writer.writerow([
            oferta.oferta.nombre,
            oferta.precio_vendedor_final,
            oferta.created_at.strftime('%Y-%m-%d %H:%M UTC'),
            oferta.distribuidor.username,
            'MXN'
        ])
    
    logger.info(f"Vendor {vendedor.username} exported offers at {timezone.now()} UTC")
    return response