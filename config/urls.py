# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.shortcuts import redirect
from django.conf import settings

# Vista de salud para monitoreo externo (no interfiere con redirección principal)
def health_check(request):
    """
    Endpoint de monitoreo: verifica que el backend está en línea.
    Ideal para servicios de Render, uptime bots o sistemas de alerta.
    """
    return HttpResponse("MexaRed está activo ✅")

# Redirección automática desde la raíz al login
def root_redirect(request):
    """
    Redirecciona automáticamente la raíz del sitio al sistema de login.
    """
    return redirect('login')  # Asegúrate que 'login' esté definido correctamente en tus urls de users o auth

urlpatterns = [
    # Panel de administración de Django
    path('admin/', admin.site.urls),

    # Vista de monitoreo del sistema
    path('health/', health_check, name='health_check'),

    # Redirección raíz hacia login
    path('', root_redirect),

    # Enrutamiento modular por aplicación
    path('users/', include('apps.users.urls')),               # Registro, login, perfiles
    path('vendedores/', include('apps.vendedores.urls')),     # Funcionalidades para vendedores
    path('lineas/', include('apps.lineas.urls', namespace='lineas')),
    path('ofertas/', include('apps.ofertas.urls')),
    path('wallet/', include('apps.wallet.urls', namespace='wallet')),
    path('activaciones/', include('apps.activaciones.urls', namespace='activaciones')),
    path('transacciones/', include('apps.transacciones.urls')),

    # Herramientas de desarrollo (solo activas si DEBUG=True)
]

# Activación del Debug Toolbar solo en entorno de desarrollo
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
