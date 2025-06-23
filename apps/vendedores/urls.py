"""
URLs para la app vendedores en MexaRed.
Define rutas para la gestión de vendedores por distribuidores, incluyendo listado,
creación, asignación/descuento de saldo, y activación/desactivación, con soporte
para internacionalización y escalabilidad global.
"""
from django.urls import path
from .views import (
    DistribuidorVendedorListView,
    DistribuidorVendedorCreateView,
    AsignarSaldoView,
    DescontarSaldoView,
    DistribuidorVendedorToggleActiveView,
    DistribuidorVendedorUpdateView,
)

app_name = 'vendedores'

urlpatterns = [
    # 📋 Listado de vendedores asignados al distribuidor autenticado
    path('', DistribuidorVendedorListView.as_view(), name='lista'),
    
    # ➕ Crear un nuevo usuario vendedor y su relación con el distribuidor
    path('crear/', DistribuidorVendedorCreateView.as_view(), name='crear'),
    
    # 💸 Asignar saldo adicional a un vendedor existente
    path('<int:pk>/asignar-saldo/', AsignarSaldoView.as_view(), name='asignar_saldo'),
    
    # 🧾 Descontar saldo disponible de un vendedor
    path('<int:pk>/descontar-saldo/', DescontarSaldoView.as_view(), name='descontar_saldo'),
    

    path('editar/<int:pk>/', DistribuidorVendedorUpdateView.as_view(), name='editar'),

    # 🔄 Activar o desactivar un vendedor
    path('<int:pk>/toggle-active/', DistribuidorVendedorToggleActiveView.as_view(), name='toggle_active'),
]