"""
URLs para la aplicación de transacciones en MexaRed.
Define rutas para la gestión de transacciones financieras, motivos y auditoría.
Soporta vistas para listar, crear, actualizar y detallar transacciones, con seguridad y escalabilidad.
"""

from django.urls import path
from apps.transacciones.views import (
    ListaTransaccionesView,
    TransaccionCreateView,
    TransaccionDetailView,
    MotivoTransaccionListView,
    MotivoTransaccionCreateView,
    MotivoTransaccionUpdateView,
)

app_name = "transacciones"

urlpatterns = [
    # 🔐 Gestión de Transacciones
    path("", ListaTransaccionesView.as_view(), name="listar"),

    path("crear/", TransaccionCreateView.as_view(), name="crear"),
    path("detalle/<int:pk>/", TransaccionDetailView.as_view(), name="detalle"),
    
    # 🧾 Gestión de Motivos de Transacción
    path("motivos/", MotivoTransaccionListView.as_view(), name="motivos"),
    path("motivos/crear/", MotivoTransaccionCreateView.as_view(), name="crear_motivo"),
    path("motivos/editar/<int:pk>/", MotivoTransaccionUpdateView.as_view(), name="editar_motivo"),
]