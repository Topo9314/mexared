# config/urls.py

from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse
from django.conf import settings



def health_check(request):
    """
    Vista rápida para validar que el backend esté corriendo correctamente.
    Ideal para pruebas de disponibilidad o monitoreo.
    """
    return HttpResponse("MexaRed está activo ✅")

urlpatterns = [
    # Panel de administración Django
    path('admin/', admin.site.urls),

    # Salud del sistema
    path('', health_check),
    path('transacciones/', include('apps.transacciones.urls')),
    # Enrutamiento modular por aplicación
    path('users/', include('apps.users.urls')),  # Gestión de usuarios (registro, login, perfiles)
    path('vendedores/', include('apps.vendedores.urls')),  # ✅ nueva ruta para la app vendedores
    # Futuras apps integradas (comentadas para activación controlada)
    path('lineas/', include('apps.lineas.urls', namespace='lineas')),
    # path('comisiones/', include('apps.comisiones.urls')),
    # path('lineas/', include('apps.lineas.urls')),
    # path('recargas/', include('apps.recargas.urls')),
    # path('reportes/', include('apps.reportes.urls')),
    # path('soporte/', include('apps.soporte.urls')),
    path('ofertas/', include('apps.ofertas.urls')),
    # path('autocomplete/', include('dal.urls')),  # Django Autocomplete Light
    # path('notificaciones/', include('apps.notificaciones.urls')),
    path('wallet/', include('apps.wallet.urls', namespace='wallet')),
    path('activaciones/', include('apps.activaciones.urls', namespace='activaciones')),

]

# Integración de Django Debug Toolbar solo en entorno de desarrollo
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
    ]
