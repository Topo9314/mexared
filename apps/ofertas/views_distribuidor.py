# apps/ofertas/views_distribuidor.py
"""
Views for distributors in the MexaRed platform, handling offer management, margin assignments,
and financial reporting. Optimized for performance, security, and international scalability.
Supports multi-currency, multi-language, and enterprise-grade auditing.
"""

import logging
import csv
import json
from decimal import Decimal, DecimalException
from django.db import transaction
from django.db.models import Sum, F, ExpressionWrapper, DecimalField, Prefetch, Count, Q
from django.http import HttpResponse, Http404, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.views.decorators.http import require_POST
from django.utils.translation import gettext_lazy as _

try:
    from django_ratelimit.decorators import ratelimit
except ImportError:
    def ratelimit(key='ip', rate='100/h', method='GET', block=True):
        def decorator(view_func):
            return view_func
        return decorator

from apps.ofertas.models import Oferta, MargenDistribuidor, MargenVendedor
from apps.ofertas.services import validate_margins, get_applicable_price, prepare_activation_data
from apps.ofertas.forms import VendedorMarginForm
from apps.ofertas.decorators import distributor_required

# Configure logging with detailed audit readiness
logger = logging.getLogger(__name__)

# Cache key prefix for distributor-specific data
CACHE_PREFIX = 'distributor_{}_'

# Global constants for template rendering control
SHOW_DESCRIPTION = True
SHOW_DURATION = True
SHOW_COMMISSIONS = True

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def distributor_dashboard(request):
    """
    Display real-time KPIs for the distributor's financial overview with caching and computed profit.
    Provides a comprehensive dashboard with offer counts, margins, and vendor statistics.
    
    Args:
        request: HTTP request object containing user and metadata.
    
    Returns:
        Rendered template with dashboard context.
    """
    distributor = request.user
    cache_key = f"{CACHE_PREFIX.format(distributor.id)}dashboard"
    context = cache.get(cache_key)

    if context is None:
        potential_profit = MargenDistribuidor.objects.filter(
            distribuidor=distributor,
            activo=True
        ).aggregate(
            total=Sum(ExpressionWrapper(
                F('precio_vendedor') - F('precio_distribuidor'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ))
        )['total'] or Decimal('0.00')

        total_vendedores = MargenVendedor.objects.filter(
            margen_distribuidor__distribuidor=distributor,
            activo=True
        ).values('vendedor').distinct().count()

        context = {
            'total_offers': Oferta.objects.filter(
                margenes_distribuidor__distribuidor=distributor,
                margenes_distribuidor__activo=True
            ).count(),
            'total_margins': MargenDistribuidor.objects.filter(
                distribuidor=distributor,
                activo=True
            ).count(),
            'potential_profit': potential_profit,
            'last_sync': Oferta.objects.latest('fecha_sincronizacion').fecha_sincronizacion if Oferta.objects.exists() else None,
            'total_vendedores': total_vendedores,
            'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
        }
        cache.set(cache_key, context, timeout=300)

    logger.info(
        f"Distributor {distributor.username} accessed dashboard from {request.META.get('REMOTE_ADDR')} "
        f"({request.META.get('HTTP_USER_AGENT')}) at {timezone.now()} UTC [Cache: {'Hit' if cache.get(cache_key) else 'Miss'}]"
    )
    return render(request, 'ofertas/distributor_dashboard.html', context)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def list_my_offers(request):
    """
    List offers with assigned margins for the distributor, optimized for search and display.
    Includes plan descriptions, durations, and net commissions for professional presentation.
    
    Args:
        request: HTTP request object containing user and query parameters.
    
    Returns:
        Rendered template with offers context.
    """
    distributor = request.user
    cache_key = f"{CACHE_PREFIX.format(distributor.id)}offers"
    context = cache.get(cache_key)

    if context is None:
        offers = MargenDistribuidor.objects.filter(
            distribuidor=distributor,
            activo=True
        ).select_related('oferta').prefetch_related(
            Prefetch('oferta__margenes_distribuidor', queryset=MargenDistribuidor.objects.filter(activo=True)),
            Prefetch('margen_vendedores', queryset=MargenVendedor.objects.filter(activo=True).select_related('vendedor'))
        ).annotate(
            total_vendors=Count('margen_vendedores__vendedor', distinct=True),
            comision_distribuidor=ExpressionWrapper(
                F('precio_vendedor') - F('precio_distribuidor'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            ),
            comision_vendedor=ExpressionWrapper(
                F('precio_cliente') - F('precio_vendedor'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        )
        search_query = request.GET.get('search', '')
        if search_query:
            offers = offers.filter(
                Q(oferta__nombre__icontains=search_query) | Q(oferta__descripcion__icontains=search_query)
            )

        context = {
            'offers': offers,
            'search_query': search_query,
            'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
            'price_policy_message': _(
                "Prices are set by the administration to ensure network integrity and fair margins. "
                "Contact us to adjust your margins."
            ),
            'include_description': SHOW_DESCRIPTION,
            'include_duration': SHOW_DURATION,
            'include_commissions': SHOW_COMMISSIONS,
        }
        cache.set(cache_key, context, timeout=300)

    logger.info(
        f"Distributor {distributor.username} viewed offers from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC [Cache: {'Hit' if cache.get(cache_key) else 'Miss'}]"
    )
    return render(request, 'ofertas/distributor_list_offers.html', context)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def view_margin_breakdown(request, offer_id):
    """
    Display detailed margin breakdown for a specific offer with enhanced security and clarity.
    Includes plan description, duration, and net commissions for distributor and vendor.
    
    Args:
        request: HTTP request object containing user and metadata.
        offer_id: ID of the offer to display.
    
    Returns:
        Rendered template with margin breakdown context.
    
    Raises:
        Http404: If the offer is invalid or inaccessible.
    """
    distributor = request.user
    try:
        margin = get_object_or_404(
            MargenDistribuidor,
            oferta_id=offer_id,
            distribuidor=distributor,
            activo=True
        )
    except Http404:
        logger.error(
            f"Distributor {distributor.username} attempted to access invalid offer {offer_id} "
            f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
        )
        raise Http404(_("The requested offer does not exist or is inaccessible."))

    negotiable_margin = margin.margen_distribuidor - (
        MargenVendedor.objects.filter(
            margen_distribuidor__distribuidor=distributor,
            margen_distribuidor__oferta=margin.oferta,
            activo=True
        ).aggregate(total=Sum('precio_vendedor'))['total'] or Decimal('0.00')
    )

    context = {
        'margin': margin,
        'breakdown': {
            'precio_distribuidor': margin.precio_distribuidor,
            'precio_vendedor': margin.precio_vendedor,
            'precio_cliente': margin.precio_cliente,
            'margen_admin': margin.margen_admin,
            'margen_distribuidor': margin.margen_distribuidor,
            'margen_vendedor': margin.margen_vendedor,
            'margen_negociable': negotiable_margin,
            'comision_distribuidor': margin.precio_vendedor - margin.precio_distribuidor,
            'comision_vendedor': margin.precio_cliente - margin.precio_vendedor,
        },
        'descripcion': margin.oferta.descripcion,
        'duracion': margin.oferta.duracion_dias,
        'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
        'price_policy_message': _(
            "Prices are fixed by administration. Commissions vary based on your configuration."
        ),
        'include_description': SHOW_DESCRIPTION,
        'include_duration': SHOW_DURATION,
        'include_commissions': SHOW_COMMISSIONS,
    }
    logger.info(
        f"Distributor {distributor.username} viewed margin breakdown for offer {offer_id} "
        f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/distributor_margin_breakdown.html', context)

@distributor_required
@require_POST
@ratelimit(key='ip', rate='20/m', method='POST', block=True)
def update_offer_margin(request, offer_id):
    """
    Update the vendor price for a specific offer via inline editing, ensuring only precio_vendedor is editable.
    Enhanced with strict validation, audit logging, and international compliance.
    
    Args:
        request: HTTP request object containing JSON payload.
        offer_id: ID of the offer to update.
    
    Returns:
        JsonResponse with success status and message.
    
    Raises:
        Http404: If the offer is invalid or inaccessible.
        ValueError, DecimalException: If the input data is invalid.
    """
    distributor = request.user
    try:
        margin = get_object_or_404(
            MargenDistribuidor,
            oferta_id=offer_id,
            distribuidor=distributor,
            activo=True
        )
        data = json.loads(request.body)
        field = data.get('field')
        new_value = Decimal(str(data.get('value', '0.00'))).quantize(Decimal('0.01'))

        # Define editable fields (only precio_vendedor is allowed)
        editable_fields = ['precio_vendedor']
        if field not in editable_fields:
            logger.warning(
                f"[SECURITY] Distributor {distributor.username} tried to update unauthorized field '{field}' "
                f"on offer {offer_id} from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
            )
            return JsonResponse({
                'success': False,
                'message': _('You are not authorized to modify this field.'),
                'original_value': str(getattr(margin, field))
            }, status=403)

        # Validate new vendor price
        current_value = getattr(margin, field)
        if new_value < margin.precio_distribuidor:
            logger.warning(
                f"[VALIDATION] Distributor {distributor.username} attempted to set precio_vendedor ({new_value}) "
                f"below precio_distribuidor ({margin.precio_distribuidor}) for offer {offer_id} "
                f"from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
            )
            return JsonResponse({
                'success': False,
                'message': _('Vendor price cannot be less than distributor price.'),
                'original_value': str(current_value)
            }, status=400)
        if new_value > margin.precio_cliente:
            logger.warning(
                f"[VALIDATION] Distributor {distributor.username} attempted to set precio_vendedor ({new_value}) "
                f"above precio_cliente ({margin.precio_cliente}) for offer {offer_id} "
                f"from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
            )
            return JsonResponse({
                'success': False,
                'message': _('Vendor price cannot exceed client price.'),
                'original_value': str(current_value)
            }, status=400)

        # Perform update with transaction
        with transaction.atomic():
            setattr(margin, field, new_value)
            margin.save(update_fields=['precio_vendedor', 'updated_at'])

            # Update related MargenVendedor instances to reflect new vendor price
            if field == 'precio_vendedor':
                MargenVendedor.objects.filter(
                    margen_distribuidor=margin,
                    activo=True
                ).update(
                    precio_vendedor=new_value,
                    updated_at=timezone.now()
                )

            # Invalidate cache for distributor offers
            cache.delete(f"{CACHE_PREFIX.format(distributor.id)}offers")
            cache.delete(f"{CACHE_PREFIX.format(distributor.id)}vendor_margins")

            logger.info(
                f"[AUDIT] Distributor {distributor.username} updated {field} to {new_value} for offer {offer_id} "
                f"from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
            )
            return JsonResponse({
                'success': True,
                'message': _('Vendor price updated successfully.'),
                'new_value': str(new_value)
            }, status=200)

    except (ValueError, DecimalException):
        logger.error(
            f"[ERROR] Distributor {distributor.username} submitted invalid data for offer {offer_id} "
            f"from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
        )
        return JsonResponse({
            'success': False,
            'message': _('Invalid numeric value.'),
            'original_value': str(getattr(margin, 'precio_vendedor'))
        }, status=400)
    except Exception as e:
        logger.error(
            f"[ERROR] Failed to update margin for offer {offer_id} by distributor {distributor.username}: {str(e)} "
            f"from IP {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
        )
        return JsonResponse({
            'success': False,
            'message': _('An error occurred. Please try again.'),
            'original_value': str(getattr(margin, 'precio_vendedor'))
        }, status=500)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def assign_vendedor_margin(request, vendedor_id):
    """
    Assign or negotiate margins with a specific vendor with enhanced validation.
    Ensures margins comply with distributor limits and updates vendor assignments.
    
    Args:
        request: HTTP request object containing form data or GET parameters.
        vendedor_id: ID of the vendor to assign margins to.
    
    Returns:
        Rendered template with form and vendor context.
    
    Raises:
        Http404: If the vendor is invalid or inaccessible.
    """
    distributor = request.user
    try:
        vendedor = get_object_or_404(
            settings.AUTH_USER_MODEL,
            id=vendedor_id,
            rol='vendedor',
            distribuidor=distributor
        )
    except Http404:
        logger.error(
            f"Distributor {distributor.username} attempted to access invalid vendor {vendedor_id} "
            f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
        )
        raise Http404(_("The requested vendor does not exist or is inaccessible."))

    if request.method == 'POST':
        form = VendedorMarginForm(request.POST)
        if form.is_valid():
            margen_distribuidor = form.cleaned_data['margen_distribuidor']
            precio_vendedor = form.cleaned_data['precio_vendedor']
            precio_cliente = form.cleaned_data['precio_cliente']
            try:
                if precio_vendedor < margen_distribuidor.precio_distribuidor or precio_vendedor > margen_distribuidor.precio_vendedor:
                    messages.error(request, _("Price must be between distributor price and allowed vendor price."))
                elif precio_cliente < precio_vendedor or precio_cliente > margen_distribuidor.precio_cliente:
                    messages.error(request, _("Client price must be between vendor price and allowed client price."))
                else:
                    with transaction.atomic():
                        MargenVendedor.objects.update_or_create(
                            margen_distribuidor=margen_distribuidor,
                            vendedor=vendedor,
                            defaults={
                                'precio_vendedor': precio_vendedor,
                                'precio_cliente': precio_cliente,
                                'activo': True
                            }
                        )
                        messages.success(
                            request,
                            _(f"Margin assigned to {vendedor.username} for {margen_distribuidor.oferta.nombre}")
                        )
                        logger.info(
                            f"Distributor {distributor.username} assigned margin {precio_vendedor} to {vendedor.username} "
                            f"for {margen_distribuidor.oferta.nombre} from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                        )
            except Exception as e:
                messages.error(request, _("An error occurred while assigning the margin."))
                logger.error(
                    f"Error assigning margin: {str(e)} from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                )
        else:
            messages.error(request, _("The form contains errors. Please verify the entered data."))
    else:
        form = VendedorMarginForm(initial={'distributor': distributor})

    context = {
        'form': form,
        'vendedor': vendedor,
        'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
    }
    logger.info(
        f"Distributor {distributor.username} accessed vendor margin assignment for {vendedor.username} "
        f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/distributor_assign_vendedor_margin.html', context)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def list_vendedor_margins(request):
    """
    List margins assigned to vendors with export option and cache optimization.
    Provides a detailed view of vendor margins with CSV export capability.
    
    Args:
        request: HTTP request object containing user and export parameters.
    
    Returns:
        Rendered template or CSV response if export is requested.
    """
    distributor = request.user
    cache_key = f"{CACHE_PREFIX.format(distributor.id)}vendor_margins"
    context = cache.get(cache_key)

    if context is None:
        margins = MargenVendedor.objects.filter(
            margen_distribuidor__distribuidor=distributor,
            activo=True
        ).select_related('margen_distribuidor', 'margen_distribuidor__oferta', 'vendedor')
        if request.GET.get('export'):
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = (
                f'attachment; filename="margenes_vendedores_{timezone.now().strftime("%Y%m%d_%H%M%S")}_UTC.csv"'
            )
            writer = csv.writer(response)
            writer.writerow(['Vendedor', 'Oferta', 'Precio Vendedor', 'Precio Cliente', 'Fecha Asignación', 'Moneda'])
            for margin in margins:
                writer.writerow([
                    margin.vendedor.username,
                    margin.margen_distribuidor.oferta.nombre,
                    f"{margin.precio_vendedor:.2f}",
                    f"{margin.precio_cliente:.2f}",
                    margin.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    margin.margen_distribuidor.moneda
                ])
            logger.info(
                f"Distributor {distributor.username} exported vendor margins from {request.META.get('REMOTE_ADDR')} "
                f"at {timezone.now()} UTC"
            )
            return response
        context = {
            'margins': margins,
            'remaining_margin': MargenDistribuidor.objects.filter(
                distribuidor=distributor,
                activo=True
            ).aggregate(
                total=Sum(ExpressionWrapper(
                    F('precio_vendedor') - F('precio_distribuidor'),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                )) - Sum('margen_vendedor')
            )['total'] or Decimal('0.00'),
            'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
        }
        cache.set(cache_key, context, timeout=300)

    logger.info(
        f"Distributor {distributor.username} viewed vendor margins from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC [Cache: {'Hit' if cache.get(cache_key) else 'Miss'}]"
    )
    return render(request, 'ofertas/distributor_list_vendedor_margins.html', context)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def sales_summary(request):
    """
    Placeholder view for sales data from activations, optimized with caching.
    To be expanded upon integration of activation data.
    
    Args:
        request: HTTP request object containing user and metadata.
    
    Returns:
        Rendered template with placeholder context.
    """
    cache_key = f"{CACHE_PREFIX.format(request.user.id)}sales_summary"
    context = cache.get(cache_key)

    if context is None:
        context = {
            'message': _("Sales summary will be available upon activations integration."),
            'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
        }
        cache.set(cache_key, context, timeout=300)

    logger.info(
        f"Distributor {request.user.username} accessed sales summary from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC [Cache: {'Hit' if cache.get(cache_key) else 'Miss'}]"
    )
    return render(request, 'ofertas/distributor_sales_summary.html', context)

@distributor_required
@ratelimit(key='ip', rate='20/m', method='GET', block=True)
def profitability_report(request):
    """
    Generate a profitability report for the distributor with enhanced export capabilities.
    Summarizes gross profit, platform, distributor, and vendor margins.
    
    Args:
        request: HTTP request object containing user and export parameters.
    
    Returns:
        Rendered template or CSV response if export is requested.
    """
    distributor = request.user
    cache_key = f"{CACHE_PREFIX.format(distributor.id)}profitability"
    context = cache.get(cache_key)

    if context is None:
        margins = MargenDistribuidor.objects.filter(distribuidor=distributor, activo=True)
        vendor_margins = MargenVendedor.objects.filter(margen_distribuidor__distribuidor=distributor, activo=True)
        context = {
            'gross_profit': margins.aggregate(total=Sum('margen_distribuidor'))['total'] or Decimal('0.00'),
            'platform_margin': margins.aggregate(total=Sum('margen_admin'))['total'] or Decimal('0.00'),
            'distributor_margin': margins.aggregate(
                total=Sum(ExpressionWrapper(
                    F('precio_vendedor') - F('precio_distribuidor'),
                    output_field=DecimalField(max_digits=10, decimal_places=2)
                ))
            )['total'] or Decimal('0.00'),
            'vendor_margin': vendor_margins.aggregate(total=Sum('margen_vendedor'))['total'] or Decimal('0.00'),
            'currency': getattr(settings, 'CURRENCY_DEFAULT', 'MXN'),
        }
        cache.set(cache_key, context, timeout=300)

    if request.GET.get('export'):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="rentabilidad_{timezone.now().strftime("%Y%m%d_%H%M%S")}_UTC.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(['Tipo', 'Monto'])
        writer.writerow(['Ganancia Bruta', f"{context['gross_profit']:.2f} {context['currency']}"])
        writer.writerow(['Margen Plataforma', f"{context['platform_margin']:.2f} {context['currency']}"])
        writer.writerow(['Margen Distribuidor', f"{context['distributor_margin']:.2f} {context['currency']}"])
        writer.writerow(['Margen Vendedor', f"{context['vendor_margin']:.2f} {context['currency']}"])
        logger.info(
            f"Distributor {distributor.username} exported profitability report from {request.META.get('REMOTE_ADDR')} "
            f"at {timezone.now()} UTC"
        )
        return response

    logger.info(
        f"Distributor {distributor.username} viewed profitability report from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC [Cache: {'Hit' if cache.get(cache_key) else 'Miss'}]"
    )
    return render(request, 'ofertas/distributor_profitability_report.html', context)