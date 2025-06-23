# apps/ofertas/urls.py

from django.urls import path

from . import views_admin, views_distribuidor, views_vendedor

app_name = 'ofertas'

urlpatterns = [

    # ==================================
    # ADMIN PANEL URLS
    # ==================================
    path('admin/', views_admin.list_offers, name='admin_list_offers'),
    path('admin/offers/sync/', views_admin.sync_addinteli_offers, name='admin_sync_offers'),
    path('admin/margins/', views_admin.list_distributor_margins, name='admin_list_margins'),
    path('admin/margins/assign/<int:distributor_id>/', views_admin.assign_margins_to_distributor, name='admin_assign_margins'),
    path('admin/special-price-list/create/', views_admin.create_special_price_list, name='admin_create_price_list'),
    path('admin/special-price-list/<int:list_id>/assign-offer/', views_admin.assign_offer_to_price_list, name='admin_assign_offer_price'),
    path('admin/special-price-list/assign-client/<int:user_id>/', views_admin.assign_price_list_to_client, name='admin_assign_client_list'),
    path('admin/audit/overview/', views_admin.audit_financial_overview, name='admin_audit_overview'),
    path('admin/sync/', views_admin.trigger_sync_offers, name='sync_offers'),  # Nueva URL
    # ==================================
    # DISTRIBUTOR PANEL URLS
    # ==================================
    path('distributor/', views_distribuidor.distributor_dashboard, name='distributor_dashboard'),
    path('distributor/my-offers/', views_distribuidor.list_my_offers, name='distributor_list_offers'),
    path('distributor/offer/<int:offer_id>/detail/', views_distribuidor.view_margin_breakdown, name='distributor_margin_detail'),
    path('distributor/vendedor/<int:vendedor_id>/assign-margin/', views_distribuidor.assign_vendedor_margin, name='distributor_assign_vendedor_margin'),
    path('distributor/vendedor-margins/', views_distribuidor.list_vendedor_margins, name='distributor_list_vendedor_margins'),
    path('distributor/profitability/', views_distribuidor.profitability_report, name='distributor_profitability'),
    path('distributor/sales-summary/', views_distribuidor.sales_summary, name='distributor_sales_summary'),
    path('update-margin/<int:offer_id>/', views_distribuidor.update_offer_margin, name='update_margin'),
    # ==================================
    # VENDOR PANEL URLS
    # ==================================
    path('vendedor/', views_vendedor.vendedor_dashboard, name='vendedor_dashboard'),
    path('vendedor/my-offers/', views_vendedor.lista_ofertas_asignadas, name='vendedor_list_offers'),
    path('vendedor/offer/<int:offer_id>/detail/', views_vendedor.detalle_margen_oferta, name='vendedor_offer_detail'),
    path('vendedor/export-offers/', views_vendedor.exportar_ofertas_vendedor, name='vendedor_export_offers'),
]