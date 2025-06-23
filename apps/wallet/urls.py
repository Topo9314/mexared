"""
URLs del módulo financiero Wallet de MexaRed.
Organiza y estructura las rutas de acceso a las vistas financieras de forma segura,
escalable y cumpliendo con arquitectura SaaS multinivel y estándares internacionales.

Incluye rutas para:
- Recarga de saldo
- Transferencias jerárquicas
- Bloqueo y desbloqueo de fondos
- Dashboard financiero con analítica
- Exportación de movimientos
- Ledger contable multinivel para auditoría contable
"""

from django.urls import path
from apps.wallet.views import (
    AdminRecargaView,
    TransferenciaView,
    BloqueoFondosView,
    DesbloqueoFondosView,
    WalletDashboardView,
    ExportMovimientosView,
)
from apps.wallet.views_ledger import (
    LedgerGlobalSummaryView,
    LedgerDistribuidorDetailView,
)

# Namespace principal de la app
app_name = "wallet"

urlpatterns = [
    # 🔐 Operaciones administrativas (solo ADMIN / permisos controlados)
    path("recarga/", AdminRecargaView.as_view(), name="recarga"),
    path("transferencia/", TransferenciaView.as_view(), name="transferencia"),
    path("bloqueo/", BloqueoFondosView.as_view(), name="bloqueo"),
    path("desbloqueo/", DesbloqueoFondosView.as_view(), name="desbloqueo"),
    
    # 📊 Dashboard financiero multinivel (ADMIN, DISTRIBUIDOR, VENDEDOR)
    path("", WalletDashboardView.as_view(), name="dashboard"),

    # 📂 Exportación de movimientos (para conciliación, fiscalización y auditoría)
    path("export/", ExportMovimientosView.as_view(), name="export_movimientos"),

    # 📚 Ledger contable multinivel (solo ADMIN o DISTRIBUIDOR autorizado)
    path("ledger/", LedgerGlobalSummaryView.as_view(), name="ledger_global"),
    path("ledger/distribuidor/<int:distribuidor_id>/", LedgerDistribuidorDetailView.as_view(), name="ledger_distribuidor"),
]
