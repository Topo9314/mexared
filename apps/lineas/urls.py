"""
URLs para el módulo de Líneas en MexaRed.
Define rutas REST y web para gestionar líneas telefónicas (SIMs).
Diseñado para entornos SaaS multinivel con arquitectura desacoplada y escalable.
Soporta nombres de espacio (namespace) para evitar conflictos y facilitar reversing.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) para APIs y vistas web.
Preparado para futuras extensiones como sincronización con Addinteli.
"""

from django.urls import path
from . import views

app_name = 'lineas'

urlpatterns = [

    # VISTAS WEB UI (Portal Interno)
    path('', views.LineaWebListView.as_view(), name='list'),  # <- Esta es la lista principal web (usamos LineaWebListView)
    path('create/', views.LineaCreateView.as_view(), name='create'),
    path('edit/<uuid:pk>/', views.LineaUpdateView.as_view(), name='edit'),
    path('detail/<uuid:pk>/', views.LineaDetailView.as_view(), name='detail'),
    path('delete/<uuid:pk>/', views.LineaDeleteView.as_view(), name='delete'),

    # VISTAS API REST (Integraciones, automatizaciones, futura integración Addinteli)
    path('api/list/', views.LineaListAPIView.as_view(), name='api_list'),
    path('api/detail/<uuid:uuid>/', views.LineaDetailAPIView.as_view(), name='api_detail'),
    path('api/create/', views.LineaCreateAPIView.as_view(), name='api_create'),
]
