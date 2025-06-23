# apps/ofertas/views_admin.py

import logging
from datetime import datetime
from typing import Optional
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseRedirect, HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
import csv
from openpyxl import Workbook
from io import BytesIO

from apps.ofertas.models import (
    Oferta,
    MargenDistribuidor,
    ListaPreciosEspecial,
    OfertaListaPreciosEspecial,
    ClienteListaAsignada,
)
from apps.ofertas.services import validate_margins
from apps.ofertas.forms import (
    OfferMarginForm,
    SpecialPriceListForm,
    OfferSpecialPriceForm,
    ClientPriceListAssignForm,
)
from apps.ofertas.permissions import is_admin
from apps.ofertas.utils.sync_addinteli import sync_addinteli_offers

# Configure logging with international audit readiness
logger = logging.getLogger(__name__)

# Default currency from settings
DEFAULT_CURRENCY = getattr(settings, 'CURRENCY_DEFAULT', 'MXN')

@login_required
@user_passes_test(is_admin)
def sync_addinteli_offers(request):
    """
    Synchronize offer catalog from Addinteli on demand with automation readiness.
    
    Supports both AJAX and standard POST requests, with audit logging and user feedback.
    """
    if request.method == 'POST':
        try:
            new_count, updated_count = sync_addinteli_offers()
            last_sync = Oferta.objects.latest('fecha_sincronizacion').fecha_sincronizacion
            success_message = _(f"Synchronization successful: {new_count} new offers created, {updated_count} updated")
            messages.success(request, success_message)
            logger.info(
                f"[AUDIT] Admin {request.user.username} triggered sync from {request.META.get('REMOTE_ADDR')} "
                f"at {timezone.now()} UTC, created {new_count}, updated {updated_count} offers"
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'success',
                    'message': str(success_message),
                    'new_count': new_count,
                    'updated_count': updated_count,
                    'last_sync': last_sync.isoformat(),
                })
            return redirect('ofertas:admin_list_offers')
        except Exception as e:
            error_message = _(f"Failed to synchronize offers: {str(e)}")
            messages.error(request, error_message)
            logger.error(
                f"[ERROR] Admin {request.user.username} failed to sync from {request.META.get('REMOTE_ADDR')} "
                f"at {timezone.now()} UTC: {str(e)}"
            )
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'status': 'error',
                    'message': str(error_message),
                }, status=500)
    return redirect('ofertas:admin_list_offers')

@login_required
@user_passes_test(is_admin)
def trigger_sync_offers(request):
    """
    Trigger offer synchronization from Addinteli via admin interface.
    
    Provides a dedicated endpoint for admin panel synchronization, with redirect to offer list.
    """
    try:
        new_count, updated_count = sync_addinteli_offers()
        success_message = _(f"Synchronization successful: {new_count} new offers created, {updated_count} updated")
        messages.success(request, success_message)
        logger.info(
            f"[AUDIT] Admin {request.user.username} triggered sync via admin from {request.META.get('REMOTE_ADDR')} "
            f"at {timezone.now()} UTC, created {new_count}, updated {updated_count} offers"
        )
    except Exception as e:
        error_message = _(f"Failed to synchronize offers: {str(e)}")
        messages.error(request, error_message)
        logger.error(
            f"[ERROR] Admin {request.user.username} failed to sync via admin from {request.META.get('REMOTE_ADDR')} "
            f"at {timezone.now()} UTC: {str(e)}"
        )
    return redirect('ofertas:admin_list_offers')

@login_required
@user_passes_test(is_admin)
def list_offers(request):
    """
    List all synchronized offers with filtering and internationalization support.
    
    Supports active-only filtering, search, and displays last synchronization time.
    """
    offers = Oferta.objects.select_related('margenes_distribuidor').order_by('-fecha_sincronizacion')
    active_only = request.GET.get('active_only', False)
    if active_only:
        offers = offers.filter(activo=True)
    
    search_query = request.GET.get('search', '')
    if search_query:
        offers = offers.filter(
            Q(codigo_addinteli__icontains=search_query) |
            Q(nombre__icontains=search_query) |
            Q(descripcion__icontains=search_query)
        )
    
    context = {
        'offers': offers,
        'last_sync': offers.latest('fecha_sincronizacion').fecha_sincronizacion if offers.exists() else None,
        'currency': DEFAULT_CURRENCY,
        'search_query': search_query,
        'active_only': active_only,
    }
    logger.info(
        f"[AUDIT] Admin {request.user.username} viewed offer list from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/admin_list_offers.html', context)

@login_required
@user_passes_test(is_admin)
def assign_margins_to_distributor(request, distributor_id):
    """
    Assign or edit margins for a specific distributor with real-time validation.
    
    Uses transactions to ensure data consistency and logs actions for audit.
    """
    distributor = get_object_or_404(settings.AUTH_USER_MODEL, id=distributor_id, rol='distribuidor')
    if request.method == 'POST':
        form = OfferMarginForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    margen, created = MargenDistribuidor.objects.update_or_create(
                        oferta=form.cleaned_data['oferta'],
                        distribuidor=distributor,
                        defaults={
                            'precio_distribuidor': form.cleaned_data['precio_distribuidor'],
                            'precio_vendedor': form.cleaned_data['precio_vendedor'],
                            'precio_cliente': form.cleaned_data['precio_cliente'],
                            'moneda': form.cleaned_data['moneda'],
                            'activo': True,
                            'fecha_asignacion': timezone.now(),
                        }
                    )
                    validate_margins(margen)
                    action = "assigned" if created else "updated"
                    messages.success(
                        request,
                        _(f"Margins {action} successfully for {margen.oferta.nombre} - {distributor.username}")
                    )
                    logger.info(
                        f"[AUDIT] Admin {request.user.username} {action} margins for {distributor.username} "
                        f"on offer {margen.oferta.nombre} from {request.META.get('REMOTE_ADDR')} "
                        f"at {timezone.now()} UTC"
                    )
                    return redirect('ofertas:admin_list_margins')
            except ValidationError as e:
                messages.error(request, str(e))
                logger.warning(
                    f"[VALIDATION] Admin {request.user.username} failed to assign margins for {distributor.username}: {str(e)}"
                )
        else:
            messages.error(request, _("Invalid form data. Please check the entered values."))
    else:
        form = OfferMarginForm(initial={'distributor': distributor})
    
    context = {
        'form': form,
        'distributor': distributor,
        'currency': DEFAULT_CURRENCY,
    }
    return render(request, 'ofertas/admin_assign_margins.html', context)

@login_required
@user_passes_test(is_admin)
def list_distributor_margins(request):
    """
    List all active distributor margins with search, export (CSV/Excel), and multi-language support.
    
    Optimized with select_related for performance and supports multi-format exports.
    """
    margins = MargenDistribuidor.objects.select_related('oferta', 'distribuidor').filter(activo=True)
    search_query = request.GET.get('search', '')
    if search_query:
        margins = margins.filter(
            Q(oferta__nombre__icontains=search_query) |
            Q(distribuidor__username__icontains=search_query)
        )
    
    export_format = request.GET.get('export', None)
    if export_format:
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        if export_format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = f'attachment; filename="margenes_distribuidores_{timestamp}_UTC.csv"'
            writer = csv.writer(response)
            writer.writerow([
                _('Distributor'),
                _('Offer'),
                _('Distributor Price'),
                _('Vendor Price'),
                _('Client Price'),
                _('Assignment Date'),
                _('Currency'),
            ])
            for margin in margins:
                writer.writerow([
                    margin.distribuidor.username,
                    margin.oferta.nombre,
                    f"{margin.precio_distribuidor:.2f}",
                    f"{margin.precio_vendedor:.2f}",
                    f"{margin.precio_cliente:.2f}",
                    margin.fecha_asignacion.strftime('%Y-%m-%d %H:%M UTC'),
                    margin.moneda,
                ])
            logger.info(
                f"[AUDIT] Admin {request.user.username} exported margins as CSV from {request.META.get('REMOTE_ADDR')} "
                f"at {timezone.now()} UTC"
            )
            return response
        elif export_format == 'excel':
            wb = Workbook()
            ws = wb.active
            ws.title = _("Distributor Margins")
            ws.append([
                _('Distributor'),
                _('Offer'),
                _('Distributor Price'),
                _('Vendor Price'),
                _('Client Price'),
                _('Assignment Date'),
                _('Currency'),
            ])
            for margin in margins:
                ws.append([
                    margin.distribuidor.username,
                    margin.oferta.nombre,
                    float(margin.precio_distribuidor),
                    float(margin.precio_vendedor),
                    float(margin.precio_cliente),
                    margin.fecha_asignacion,
                    margin.moneda,
                ])
            output = BytesIO()
            wb.save(output)
            output.seek(0)
            response = HttpResponse(
                content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                content=output.read(),
            )
            response['Content-Disposition'] = f'attachment; filename="margenes_distribuidores_{timestamp}_UTC.xlsx"'
            logger.info(
                f"[AUDIT] Admin {request.user.username} exported margins as Excel from {request.META.get('REMOTE_ADDR')} "
                f"at {timezone.now()} UTC"
            )
            return response
    
    context = {
        'margins': margins,
        'search_query': search_query,
        'currency': DEFAULT_CURRENCY,
    }
    logger.info(
        f"[AUDIT] Admin {request.user.username} viewed distributor margins from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/admin_list_margins.html', context)

@login_required
@user_passes_test(is_admin)
def create_special_price_list(request):
    """
    Create a new special price list with internationalization support.
    
    Logs creation actions for audit and redirects to list view on success.
    """
    if request.method == 'POST':
        form = SpecialPriceListForm(request.POST)
        if form.is_valid():
            try:
                lista = form.save()
                messages.success(request, _(f"Price list {lista.nombre} created successfully"))
                logger.info(
                    f"[AUDIT] Admin {request.user.username} created special price list {lista.nombre} "
                    f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                )
                return redirect('ofertas:admin_list_price_lists')
            except Exception as e:
                messages.error(request, _(f"Failed to create price list: {str(e)}"))
                logger.error(
                    f"[ERROR] Admin {request.user.username} failed to create price list: {str(e)} "
                    f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                )
    else:
        form = SpecialPriceListForm()
    
    context = {
        'form': form,
        'currency': DEFAULT_CURRENCY,
    }
    return render(request, 'ofertas/admin_create_price_list.html', context)

@login_required
@user_passes_test(is_admin)
def assign_offer_to_price_list(request, list_id):
    """
    Assign special prices to offers within a VIP list with validation.
    
    Ensures prices are above base cost and logs actions for audit.
    """
    lista = get_object_or_404(ListaPreciosEspecial, id=list_id, activo=True)
    if request.method == 'POST':
        form = OfferSpecialPriceForm(request.POST)
        if form.is_valid():
            try:
                oferta = form.cleaned_data['oferta']
                precio = form.cleaned_data['precio_cliente_especial']
                with transaction.atomic():
                    OfertaListaPreciosEspecial.objects.update_or_create(
                        lista=lista,
                        oferta=oferta,
                        defaults={'precio_cliente_especial': precio}
                    )
                    messages.success(
                        request,
                        _(f"Price assigned to {oferta.nombre} in {lista.nombre}")
                    )
                    logger.info(
                        f"[AUDIT] Admin {request.user.username} assigned price {precio} to {oferta.nombre} "
                        f"in {lista.nombre} from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                    )
                    return redirect('ofertas:admin_list_price_lists')
            except ValidationError as e:
                messages.error(request, str(e))
                logger.warning(
                    f"[VALIDATION] Admin {request.user.username} failed to assign price to {lista.nombre}: {str(e)}"
                )
    else:
        form = OfferSpecialPriceForm()
    
    context = {
        'form': form,
        'lista': lista,
        'offers': Oferta.objects.filter(activo=True),
        'currency': DEFAULT_CURRENCY,
    }
    return render(request, 'ofertas/admin_assign_offer_price.html', context)

@login_required
@user_passes_test(is_admin)
def assign_price_list_to_client(request, user_id):
    """
    Assign a special price list to a client with audit logging.
    
    Uses transactions for consistency and redirects to client list on success.
    """
    client = get_object_or_404(settings.AUTH_USER_MODEL, id=user_id, rol='cliente')
    if request.method == 'POST':
        form = ClientPriceListAssignForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    lista = form.cleaned_data['lista']
                    ClienteListaAsignada.objects.update_or_create(
                        cliente=client,
                        defaults={'lista': lista, 'fecha_asignacion': timezone.now()}
                    )
                    messages.success(
                        request,
                        _(f"Price list {lista.nombre} assigned to {client.username}")
                    )
                    logger.info(
                        f"[AUDIT] Admin {request.user.username} assigned {lista.nombre} to {client.username} "
                        f"from {request.META.get('REMOTE_ADDR')} at {timezone.now()} UTC"
                    )
                    return redirect('ofertas:admin_list_price_lists')
            except Exception as e:
                messages.error(request, _(f"Failed to assign price list: {str(e)}"))
                logger.error(
                    f"[ERROR] Admin {request.user.username} failed to assign price list to {client.username}: {str(e)}"
                )
    else:
        form = ClientPriceListAssignForm()
    
    context = {
        'form': form,
        'client': client,
        'currency': DEFAULT_CURRENCY,
    }
    return render(request, 'ofertas/admin_assign_client_list.html', context)

@login_required
@user_passes_test(is_admin)
def audit_financial_overview(request):
    """
    Provide a financial audit dashboard with internationalization.
    
    Aggregates key metrics and supports export to CSV for reporting.
    """
    overview = {
        'total_offers': Oferta.objects.filter(activo=True).count(),
        'total_margins': MargenDistribuidor.objects.filter(activo=True).count(),
        'total_vip_lists': ListaPreciosEspecial.objects.filter(activo=True).count(),
        'total_vip_clients': ClienteListaAsignada.objects.count(),
        'last_sync': Oferta.objects.latest('fecha_sincronizacion').fecha_sincronizacion if Oferta.objects.exists() else None,
        'currency': DEFAULT_CURRENCY,
    }
    
    if request.GET.get('export'):
        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="financial_audit_{timestamp}_UTC.csv"'
        writer = csv.writer(response)
        writer.writerow([
            _('Metric'),
            _('Value'),
        ])
        writer.writerow([_('Total Active Offers'), overview['total_offers']])
        writer.writerow([_('Total Active Margins'), overview['total_margins']])
        writer.writerow([_('Total VIP Price Lists'), overview['total_vip_lists']])
        writer.writerow([_('Total VIP Clients'), overview['total_vip_clients']])
        writer.writerow([_('Last Synchronization'), overview['last_sync'] or '-'])
        writer.writerow([_('Currency'), overview['currency']])
        logger.info(
            f"[AUDIT] Admin {request.user.username} exported financial audit from {request.META.get('REMOTE_ADDR')} "
            f"at {timezone.now()} UTC"
        )
        return response
    
    context = {'overview': overview}
    logger.info(
        f"[AUDIT] Admin {request.user.username} viewed financial audit from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/admin_audit_overview.html', context)

@login_required
@user_passes_test(is_admin)
def list_special_price_lists(request):
    """
    List all special price lists with filtering and internationalization support.
    """
    price_lists = ListaPreciosEspecial.objects.filter(activo=True).order_by('-fecha_creacion')
    context = {
        'price_lists': price_lists,
        'currency': DEFAULT_CURRENCY,
    }
    logger.info(
        f"[AUDIT] Admin {request.user.username} viewed special price lists from {request.META.get('REMOTE_ADDR')} "
        f"at {timezone.now()} UTC"
    )
    return render(request, 'ofertas/admin_list_price_lists.html', context)