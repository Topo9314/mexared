"""
Vistas para el módulo de Líneas en MexaRed.
Proporcionan endpoints REST y vistas web para gestionar líneas telefónicas (SIMs).
Diseñadas para entornos SaaS multinivel con jerarquías (Admin, Distribuidor, Vendedor).
Soportan permisos jerárquicos, auditoría, internacionalización e integración con Addinteli v8.0 API.
Cumplen con estándares internacionales (PCI DSS, SOC2, ISO 27001) para seguridad y escalabilidad.
"""

import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models, transaction
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView
from rest_framework import generics, permissions
from rest_framework.views import APIView
from rest_framework.exceptions import PermissionDenied, APIException
from rest_framework.permissions import IsAuthenticated
from django.http import JsonResponse
from apps.lineas.models import Linea
from apps.lineas.serializers import LineaReadSerializer, LineaCreateSerializer
from apps.lineas.forms import LineaForm
from apps.users.models import User, UserChangeLog, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from integraciones.apis import addinteli_lineas as api_lineas

# Configuración de logging para auditoría en producción
logger = logging.getLogger(__name__)

class LineaPermission(permissions.BasePermission):
    """
    Permiso jerárquico multinivel para acceso a líneas.
    Admin: Acceso completo.
    Distribuidor: Acceso a sus propias líneas.
    Vendedor: Acceso a las líneas asignadas.
    """
    def has_permission(self, request, view):
        """
        Verifica si el usuario está autenticado.
        """
        if not request.user or not request.user.is_authenticated:
            self.message = _("Autenticación requerida")
            logger.warning(
                f"Intento de acceso no autenticado a {view.__class__.__name__} "
                f"desde {request.META.get('REMOTE_ADDR', 'unknown')}",
                extra={"event": "addinteli"}
            )
            return False
        return True

    def has_object_permission(self, request, view, obj):
        """
        Verifica permisos a nivel de objeto según la jerarquía.
        """
        user = request.user
        if user.rol == ROLE_ADMIN:
            return True
        if user.rol == ROLE_DISTRIBUIDOR and obj.distribuidor == user:
            return True
        if user.rol == ROLE_VENDEDOR and obj.vendedor == user:
            return True
        logger.warning(
            f"Acceso denegado a línea {obj.msisdn} para usuario {user.username} "
            f"(rol: {user.rol}) desde {request.META.get('REMOTE_ADDR', 'unknown')}",
            extra={"event": "addinteli"}
        )
        return False

class LineaListView(LoginRequiredMixin, ListView):
    """
    Vista web para listar líneas según la jerarquía del usuario.
    Admin: Todas las líneas.
    Distribuidor: Líneas asignadas a él.
    Vendedor: Líneas asignadas a él.
    Soporta filtros, búsqueda y paginación.
    """
    model = Linea
    template_name = 'lineas/lineas_list.html'
    context_object_name = 'lineas'
    paginate_by = 25

    def get_queryset(self):
        """
        Filtra el queryset según el rol del usuario y aplica filtros de búsqueda.
        Optimiza consultas con select_related.
        """
        user = self.request.user
        qs = Linea.objects.select_related('distribuidor', 'vendedor')

        # Filtrar por rol
        if user.rol == ROLE_DISTRIBUIDOR:
            qs = qs.filter(distribuidor=user)
        elif user.rol == ROLE_VENDEDOR:
            qs = qs.filter(vendedor=user)

        # Aplicar filtros
        search = self.request.GET.get('search', '')
        estado = self.request.GET.get('estado', '')
        distribuidor_id = self.request.GET.get('distribuidor', '')
        categoria_servicio = self.request.GET.get('categoria_servicio', '')
        expiring_soon = self.request.GET.get('expiring_soon', '')
        expired = self.request.GET.get('expired', '')

        if search:
            qs = qs.filter(models.Q(msisdn__icontains=search) | models.Q(iccid__icontains=search))
        if estado:
            qs = qs.filter(estado=estado)
        if distribuidor_id and user.rol == ROLE_ADMIN:
            qs = qs.filter(distribuidor_id=distribuidor_id)
        if categoria_servicio:
            qs = qs.filter(categoria_servicio=categoria_servicio)
        if expiring_soon == 'true':
            now = timezone.now()
            qs = qs.filter(
                fecha_vencimiento_plan__gte=now,
                fecha_vencimiento_plan__lte=now + timezone.timedelta(days=7),
                estado__in=['assigned', 'processing']
            )
        if expired == 'true':
            now = timezone.now()
            qs = qs.filter(
                fecha_vencimiento_plan__lt=now,
                estado__in=['assigned', 'processing']
            )

        return qs.order_by('-fecha_registro')

    def get_context_data(self, **kwargs):
        """
        Proporciona el contexto para la plantilla, incluyendo filtros y distribuidores.
        """
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Filtros adicionales para Admin
        if user.rol == ROLE_ADMIN:
            context['distribuidores'] = User.objects.filter(rol=ROLE_DISTRIBUIDOR).order_by('username')

        # Preservar filtros en la paginación
        context['search'] = self.request.GET.get('search', '')
        context['estado'] = self.request.GET.get('estado', '')
        context['distribuidor'] = self.request.GET.get('distribuidor', '')
        context['categoria_servicio'] = self.request.GET.get('categoria_servicio', '')
        context['expiring_soon'] = self.request.GET.get('expiring_soon', '')
        context['expired'] = self.request.GET.get('expired', '')

        logger.info(
            f"Usuario {user.username} (rol: {user.rol}) consultó lista de líneas web "
            f"con filtros: search={context['search']}, estado={context['estado']}, "
            f"distribuidor={context['distribuidor']}, expiring_soon={context['expiring_soon']}, "
            f"expired={context['expired']}, categoria_servicio={context['categoria_servicio']}",
            extra={"event": "addinteli"}
        )
        return context

class LineaCreateView(LoginRequiredMixin, CreateView):
    """
    Vista web para crear nuevas líneas (solo para Admins).
    Registra auditoría completa y valida jerarquías.
    """
    model = Linea
    form_class = LineaForm
    template_name = 'lineas/lineas_create.html'
    success_url = reverse_lazy('lineas:list')

    def dispatch(self, request, *args, **kwargs):
        """
        Restringe acceso a superusuarios.
        """
        if not request.user.is_superuser:
            logger.warning(
                f"Intento de creación de línea denegado para {request.user.username} (no superusuario)",
                extra={"event": "addinteli"}
            )
            raise PermissionDenied(_("Solo los administradores pueden crear líneas."))
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, *args, **kwargs):
        """
        Pasa el usuario actual al formulario para auditoría.
        """
        form = super().get_form(*args, **kwargs)
        form.user = self.request.user
        return form

    def form_valid(self, form):
        """
        Asigna el usuario creador y registra la acción.
        """
        form.instance.creado_por = self.request.user
        response = super().form_valid(form)
        logger.info(
            f"Usuario {self.request.user.username} creó línea {form.instance.msisdn} "
            f"(ICCID: {form.instance.iccid}, estado: {form.instance.estado})",
            extra={"event": "addinteli"}
        )
        return response

class LineaUpdateView(LoginRequiredMixin, UpdateView):
    """
    Vista web para editar líneas existentes (solo para Admins).
    Registra auditoría completa y valida jerarquías.
    """
    model = Linea
    form_class = LineaForm
    template_name = 'lineas/lineas_update.html'
    success_url = reverse_lazy('lineas:list')

    def dispatch(self, request, *args, **kwargs):
        """
        Restringe acceso a superusuarios.
        """
        if not request.user.is_superuser:
            logger.warning(
                f"Intento de edición de línea denegado para {request.user.username} (no superusuario)",
                extra={"event": "addinteli"}
            )
            raise PermissionDenied(_("Solo los administradores pueden editar líneas."))
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, *args, **kwargs):
        """
        Pasa el usuario actual al formulario para auditoría.
        """
        form = super().get_form(*args, **kwargs)
        form.user = self.request.user
        return form

    def form_valid(self, form):
        """
        Asigna el usuario actualizador y registra la acción.
        """
        form.instance.actualizado_por = self.request.user
        response = super().form_valid(form)
        logger.info(
            f"Usuario {self.request.user.username} actualizó línea {form.instance.msisdn} "
            f"(ICCID: {form.instance.iccid}, estado: {form.instance.estado})",
            extra={"event": "addinteli"}
        )
        return response

class LineaDetailView(LoginRequiredMixin, DetailView):
    """
    Vista web para consultar el detalle de una línea individual.
    Restringida por permisos jerárquicos.
    """
    model = Linea
    template_name = 'lineas/lineas_detail.html'
    context_object_name = 'linea'

    def get_queryset(self):
        """
        Optimiza consulta con select_related y aplica permisos.
        """
        return Linea.objects.select_related('distribuidor', 'vendedor', 'creado_por', 'actualizado_por')

    def dispatch(self, request, *args, **kwargs):
        """
        Aplica permisos jerárquicos para acceso al detalle.
        """
        obj = self.get_object()
        user = request.user
        if user.rol == ROLE_ADMIN or \
           (user.rol == ROLE_DISTRIBUIDOR and obj.distribuidor == user) or \
           (user.rol == ROLE_VENDEDOR and obj.vendedor == user):
            return super().dispatch(request, *args, **kwargs)
        logger.warning(
            f"Acceso denegado a detalle de línea {obj.msisdn} para usuario {user.username} "
            f"(rol: {user.rol})",
            extra={"event": "addinteli"}
        )
        raise PermissionDenied(_("No tienes permiso para ver esta línea."))

    def get(self, request, *args, **kwargs):
        """
        Registra el acceso al detalle en el log.
        """
        instance = self.get_object()
        logger.info(
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó detalle de línea {instance.msisdn}",
            extra={"event": "addinteli"}
        )
        return super().get(request, *args, **kwargs)

class LineaDeleteView(LoginRequiredMixin, DeleteView):
    """
    Vista web para eliminación lógica de líneas (solo para Admins).
    Llama a la API de Addinteli para cancelar la línea y marca como 'cancelled' localmente.
    Registra auditoría completa.
    """
    model = Linea
    template_name = 'lineas/lineas_confirm_delete.html'
    success_url = reverse_lazy('lineas:list')

    def dispatch(self, request, *args, **kwargs):
        """
        Restringe acceso a superusuarios.
        """
        if not request.user.is_superuser:
            logger.warning(
                f"Intento de eliminación de línea denegado para {request.user.username} (no superusuario)",
                extra={"event": "addinteli"}
            )
            raise PermissionDenied(_("Solo los administradores pueden eliminar líneas."))
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        """
        Realiza eliminación lógica marcando la línea como 'cancelled' tras llamar a la API.
        """
        obj = self.get_object()
        try:
            with transaction.atomic():
                # Llamar a la API para cancelar la línea
                result = api_lineas.cancelar_linea({"icc": obj.iccid})
                if result.get('status') != 'success':
                    logger.error(
                        f"Error al cancelar línea {obj.msisdn} (ICCID: {obj.iccid}) en addinteli_lineas: {result.get('error')}",
                        extra={"event": "addinteli"}
                    )
                    raise PermissionDenied(_("Error al cancelar la línea en Addinteli: ") + str(result.get('error')))
                
                # Actualizar campos locales
                obj.estado = 'cancelled'
                obj.fecha_baja = timezone.now()
                obj.actualizado_por = request.user
                obj.reference_id = result.get('reference_id')
                obj.altan_id = result.get('altan_id')
                obj.estado_api = result
                obj.save()

                # Registrar auditoría
                UserChangeLog.objects.create(
                    user=request.user,
                    changed_by=request.user,
                    change_type='update',
                    change_description=_("Cancelación de línea"),
                    details={
                        "msisdn": obj.msisdn,
                        "iccid": obj.iccid,
                        "estado": obj.estado,
                        "reference_id": obj.reference_id,
                        "altan_id": obj.altan_id,
                        "timestamp": timezone.now().isoformat()
                    }
                )
                logger.info(
                    f"Usuario {self.request.user.username} marcó línea {obj.msisdn} como cancelada "
                    f"(ICCID: {obj.iccid}, ref: {obj.reference_id})",
                    extra={"event": "addinteli"}
                )
        except Exception as e:
            logger.error(
                f"Error al eliminar línea {obj.msisdn} por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            raise PermissionDenied(_("Error al cancelar la línea: ") + str(e))
        return super().delete(request, *args, **kwargs)

# Nuevas vistas API
# Todas las llamadas externas pasan por integraciones/apis/addinteli_lineas – no usar requests/httpx aquí.
# Los errores de Addinteli (code, description) se propagan como APIException con atributo code,
# permitiendo al frontend manejar códigos específicos (e.g., 1027 para línea ya suspendida).
class LineaListAPIView(generics.ListAPIView):
    """
    Vista API para listar líneas según la jerarquía del usuario.
    Admin: Todas las líneas.
    Distribuidor: Líneas asignadas a él.
    Vendedor: Líneas asignadas a él.
    Soporta filtros y paginación para alto volumen.
    """
    serializer_class = LineaReadSerializer
    permission_classes = [LineaPermission]

    def get_queryset(self):
        """
        Filtra el queryset según el rol del usuario.
        Optimiza consultas con select_related.
        """
        user = self.request.user
        qs = Linea.objects.select_related('distribuidor', 'vendedor').all()

        if user.rol == ROLE_ADMIN:
            return qs
        if user.rol == ROLE_DISTRIBUIDOR:
            return qs.filter(distribuidor=user)
        if user.rol == ROLE_VENDEDOR:
            return qs.filter(vendedor=user)

        logger.warning(
            f"Usuario {user.username} (rol: {user.rol}) intentó acceder a líneas sin permisos",
            extra={"event": "addinteli"}
        )
        return Linea.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Registra el acceso a la lista de líneas en el log.
        """
        logger.info(
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó lista de líneas API",
            extra={"event": "addinteli"}
        )
        return super().get(request, *args, **kwargs)

class LineaDetailAPIView(generics.RetrieveAPIView):
    """
    Vista API para consultar el detalle de una línea individual.
    Restringida por permisos jerárquicos.
    """
    serializer_class = LineaReadSerializer
    permission_classes = [LineaPermission]
    queryset = Linea.objects.select_related('distribuidor', 'vendedor').all()
    lookup_field = 'uuid'

    def get(self, request, *args, **kwargs):
        """
        Registra el acceso al detalle de una línea en el log.
        """
        instance = self.get_object()
        logger.info(
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó detalle de línea {instance.msisdn}",
            extra={"event": "addinteli"}
        )
        return super().get(request, *args, **kwargs)

class LineaCreateAPIView(generics.CreateAPIView):
    """
    Vista API para crear nuevas líneas (solo para Admins).
    Usada para cargas internas o sincronizaciones iniciales.
    Registra auditoría completa y valida jerarquías.
    """
    serializer_class = LineaCreateSerializer
    permission_classes = [permissions.IsAdminUser]

    def perform_create(self, serializer):
        """
        Crea la línea con el usuario autenticado como creador.
        """
        serializer.save(creado_por=self.request.user)
        instance = serializer.instance
        logger.info(
            f"Usuario {self.request.user.username} creó línea {instance.msisdn} "
            f"(ICCID: {instance.iccid}, estado: {instance.estado})",
            extra={"event": "addinteli"}
        )

    def create(self, request, *args, **kwargs):
        """
        Maneja la creación con auditoría y manejo de excepciones.
        """
        try:
            return super().create(request, *args, **kwargs)
        except Exception as e:
            logger.error(
                f"Error al crear línea por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            raise PermissionDenied(_("Error al crear la línea: ") + str(e))

class APILineasDisponiblesView(APIView):
    """
    Vista API para consultar líneas disponibles desde la API de Addinteli.
    Admin: Todas las líneas.
    Distribuidor: Líneas asignadas a él.
    Vendedor: Líneas asignadas a él.
    """
    permission_classes = [IsAuthenticated, LineaPermission]

    def get(self, request, *args, **kwargs):
        """
        Consulta líneas desde Addinteli y filtra según jerarquía del usuario.
        """
        try:
            user = request.user
            data = api_lineas.consultar_inventario_distribuidor()
            data_lines = data.get("data", [])

            # Filtrar líneas según rol del usuario
            if user.rol != ROLE_ADMIN:
                user_lines = Linea.objects.filter(
                    models.Q(distribuidor=user) | models.Q(vendedor=user)
                ).values_list('iccid', flat=True)
                data_lines = [
                    line for line in data_lines
                    if line.get('iccid') in user_lines
                ]

            logger.info(
                f"Usuario {user.username} (rol: {user.rol}) consultó líneas disponibles desde addinteli_lineas",
                extra={"event": "addinteli"}
            )
            return JsonResponse({**data, "data": data_lines})
        except Exception as e:
            logger.error(
                f"Error al consultar líneas desde addinteli_lineas por {request.user.username}: {str(e)}",
                extra={"event": "addinteli"}
            )
            return JsonResponse(
                {"error": _("Error al consultar líneas en Addinteli: ") + str(e)},
                status=500
            )

class SuspenderLineaAPIView(APIView):
    """
    Vista API para suspender una línea activa por ICCID vía Addinteli API.
    Restringida por permisos jerárquicos.
    """
    permission_classes = [IsAuthenticated, LineaPermission]

    def post(self, request, *args, **kwargs):
        """
        Suspende una línea y actualiza el modelo local con la respuesta de la API.
        """
        iccid = request.data.get('iccid')
        if not iccid:
            logger.warning(
                f"Intento de suspensión sin ICCID por {request.user.username}",
                extra={"event": "addinteli"}
            )
            return JsonResponse({"error": _("ICCID es requerido")}, status=400)

        try:
            with transaction.atomic():
                # Validar existencia de la línea
                line = Linea.objects.select_for_update().filter(iccid=iccid).first()
                if not line:
                    logger.warning(
                        f"Línea con ICCID {iccid} no encontrada por {request.user.username}",
                        extra={"event": "addinteli"}
                    )
                    return JsonResponse({"error": _("Línea no encontrada")}, status=404)

                # Validar permisos sobre la línea
                self.check_object_permissions(request, line)

                # Llamar a la API para suspender la línea
                result = api_lineas.suspender_linea({"icc": iccid})
                if result.get('status') != 'success':
                    logger.error(
                        f"Error al suspender línea {iccid} en addinteli_lineas: {result.get('error')}",
                        extra={"event": "addinteli"}
                    )
                    return JsonResponse(
                        {"error": _("Error al suspender la línea en Addinteli: ") + str(result.get('error'))},
                        status=400
                    )

                # Actualizar campos locales
                line.estado = 'suspended'
                line.fecha_suspension = timezone.now()
                line.actualizado_por = request.user
                line.reference_id = result.get('reference_id')
                line.altan_id = result.get('altan_id')
                line.estado_api = result
                line.save()

                # Registrar auditoría
                UserChangeLog.objects.create(
                    user=request.user,
                    changed_by=request.user,
                    change_type='update',
                    change_description=_("Suspensión de línea"),
                    details={
                        "msisdn": line.msisdn,
                        "iccid": iccid,
                        "estado": line.estado,
                        "reference_id": line.reference_id,
                        "altan_id": line.altan_id,
                        "timestamp": timezone.now().isoformat()
                    }
                )
                logger.info(
                    f"Usuario {request.user.username} suspendió línea {line.msisdn} "
                    f"(ICCID: {iccid}, ref: {line.reference_id})",
                    extra={"event": "addinteli"}
                )
                return JsonResponse(result)
        except APIException as e:
            logger.error(
                f"Error al suspender línea {iccid} por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            status_code = 409 if getattr(e, "code", None) == 1027 else 500
            return JsonResponse(
                {"error": _("Error al suspender la línea: ") + str(e)},
                status=status_code
            )
        except Exception as e:
            logger.error(
                f"Error al suspender línea {iccid} por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            return JsonResponse(
                {"error": _("Error al suspender la línea: ") + str(e)},
                status=500
            )

class CancelarLineaAPIView(APIView):
    """
    Vista API para cancelar una línea por ICCID vía Addinteli API.
    Restringida por permisos jerárquicos (solo Admins).
    """
    permission_classes = [IsAuthenticated, permissions.IsAdminUser]

    def post(self, request, *args, **kwargs):
        """
        Cancela una línea y actualiza el modelo local con la respuesta de la API.
        """
        iccid = request.data.get('iccid')
        if not iccid:
            logger.warning(
                f"Intento de cancelación sin ICCID por {request.user.username}",
                extra={"event": "addinteli"}
            )
            return JsonResponse({"error": _("ICCID es requerido")}, status=400)

        try:
            with transaction.atomic():
                # Validar existencia de la línea
                line = Linea.objects.select_for_update().filter(iccid=iccid).first()
                if not line:
                    logger.warning(
                        f"Línea con ICCID {iccid} no encontrada por {request.user.username}",
                        extra={"event": "addinteli"}
                    )
                    return JsonResponse({"error": _("Línea no encontrada")}, status=404)

                # Llamar a la API para cancelar la línea
                result = api_lineas.cancelar_linea({"icc": iccid})
                if result.get('status') != 'success':
                    logger.error(
                        f"Error al cancelar línea {iccid} en addinteli_lineas: {result.get('error')}",
                        extra={"event": "addinteli"}
                    )
                    return JsonResponse(
                        {"error": _("Error al cancelar la línea en Addinteli: ") + str(result.get('error'))},
                        status=400
                    )

                # Actualizar campos locales
                line.estado = 'cancelled'
                line.fecha_baja = timezone.now()
                line.actualizado_por = request.user
                line.reference_id = result.get('reference_id')
                line.altan_id = result.get('altan_id')
                line.estado_api = result
                line.save()

                # Registrar auditoría
                UserChangeLog.objects.create(
                    user=request.user,
                    changed_by=request.user,
                    change_type='update',
                    change_description=_("Cancelación de línea"),
                    details={
                        "msisdn": line.msisdn,
                        "iccid": iccid,
                        "estado": line.estado,
                        "reference_id": line.reference_id,
                        "altan_id": line.altan_id,
                        "timestamp": timezone.now().isoformat()
                    }
                )
                logger.info(
                    f"Usuario {request.user.username} canceló línea {line.msisdn} "
                    f"(ICCID: {iccid}, ref: {line.reference_id})",
                    extra={"event": "addinteli"}
                )
                return JsonResponse(result)
        except Exception as e:
            logger.error(
                f"Error al cancelar línea {iccid} por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            return JsonResponse(
                {"error": _("Error al cancelar la línea: ") + str(e)},
                status=500
            )

class ObtenerInfoLineaAPIView(APIView):
    """
    Vista API para consultar bolsas de beneficios (datos, SMS, voz) de una línea por MSISDN vía Addinteli API.
    Restringida por permisos jerárquicos.
    """
    permission_classes = [IsAuthenticated, LineaPermission]

    def get(self, request, msisdn, *args, **kwargs):
        """
        Consulta bolsas de beneficios desde Addinteli y retorna la respuesta.
        """
        try:
            # Validar existencia de la línea
            line = Linea.objects.filter(msisdn=msisdn).first()
            if not line:
                logger.warning(
                    f"Línea con MSISDN {msisdn} no encontrada por {request.user.username}",
                    extra={"event": "addinteli"}
                )
                return JsonResponse({"error": _("Línea no encontrada")}, status=404)

            # Validar permisos sobre la línea
            self.check_object_permissions(request, line)

            # Llamar a la API para consultar bolsas
            result = api_lineas.consultar_bolsas(msisdn=msisdn)
            if result.get('status') != 'success':
                logger.error(
                    f"Error al consultar bolsas para MSISDN {msisdn} en addinteli_lineas: {result.get('error')}",
                    extra={"event": "addinteli"}
                )
                return JsonResponse(
                    {"error": _("Error al consultar bolsas en Addinteli: ") + str(result.get('error'))},
                    status=400
                )

            logger.info(
                f"Usuario {request.user.username} (rol: {request.user.rol}) consultó bolsas de línea {msisdn}",
                extra={"event": "addinteli"}
            )
            return JsonResponse(result)
        except Exception as e:
            logger.error(
                f"Error al consultar bolsas para MSISDN {msisdn} por {request.user.username} en addinteli_lineas: {str(e)}",
                extra={"event": "addinteli"}
            )
            return JsonResponse(
                {"error": _("Error al consultar bolsas: ") + str(e)},
                status=500
            )
        



