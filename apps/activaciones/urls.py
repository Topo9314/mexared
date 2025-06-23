"""
urls.py - Configuración de URLs para el módulo de activaciones en MexaRed.
Define rutas para vistas HTML y API, con soporte para namespaces.
Optimizado para claridad, seguridad y escalabilidad.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

app_name = 'activaciones'

# Configurar router para API
router = DefaultRouter()
router.register(r'api', views.ActivacionViewSet, basename='activacion')

urlpatterns = [
    path('', views.listado_activaciones_html, name='listado_activaciones'),
    path('crear/', views.crear_activacion_html, name='crear_activacion_html'),
    path('detalle/<uuid:pk>/', views.detalle_activacion, name='detalle_activacion'),
    path('auditoria/', views.list_audit_logs_html, name='list_audit_logs'),
    path('get-planes-por-tipo/', views.get_planes_por_tipo, name='get_planes_por_tipo'),
    path('get-product-type-by-iccid/', views.get_product_type_by_iccid, name='get_product_type_by_iccid'),
    path('api/', include(router.urls)),  # Prefixed API routes
]