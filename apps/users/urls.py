"""
URLs para la aplicación de usuarios en MexaRed.
Define rutas para autenticación, clientes, vendedores y distribuidores.
"""

from django.urls import path
from .core_views import (
    login_view,
    logout_view,
    register_view,
    dashboard_redirect,
)
from .views.cliente_views import (
    cliente_register_view,
    panel_cliente,
    editar_perfil_cliente,
)
from .views.vendedor_views import (
    vendedor_dashboard,
    editar_perfil_vendedor,
    registrar_cliente_por_vendedor,
    listado_clientes_captados,
    detalle_cliente_captado,
    historial_comisiones,
    soporte_vendedor,
)
from .views.distribuidor_views import (
    panel_distribuidor,
    editar_perfil_distribuidor,
)

app_name = "users"

urlpatterns = [
    # 🔐 Autenticación
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("registro/", register_view, name="cliente_register"),
    path("dashboard/", dashboard_redirect, name="dashboard_redirect"),

    # 👤 Cliente
    path("cliente/registro/", cliente_register_view, name="registro_cliente_directo"),
    path("cliente/panel/", panel_cliente, name="panel_cliente"),
    path("cliente/editar-perfil/", editar_perfil_cliente, name="editar_perfil_cliente"),

    # 🛍️ Vendedor
    path("vendedor/", vendedor_dashboard, name="dashboard_vendedor"),
    path("vendedor/editar-perfil/", editar_perfil_vendedor, name="editar_perfil_vendedor"),
    path("vendedor/registrar-cliente/", registrar_cliente_por_vendedor, name="registrar_cliente_por_vendedor"),
    path("vendedor/clientes/", listado_clientes_captados, name="listado_clientes_captados"),
    path("vendedor/cliente/<int:cliente_id>/", detalle_cliente_captado, name="detalle_cliente_captado"),
    path("vendedor/comisiones/", historial_comisiones, name="historial_comisiones"),
    path("vendedor/soporte/", soporte_vendedor, name="soporte_vendedor"),

    # 🏢 Distribuidor
    path("distribuidor/panel/", panel_distribuidor, name="panel_distribuidor"),
    path("distribuidor/editar-perfil/", editar_perfil_distribuidor, name="editar_perfil_distribuidor"),
]