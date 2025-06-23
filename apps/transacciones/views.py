"""
Vistas para la app transacciones en MexaRed.
Proporciona una interfaz robusta, segura y escalable para gestionar transacciones financieras y motivos,
con seguridad empresarial, auditoría detallada, filtros avanzados, y optimización para entornos de alto volumen.
Diseñado con separación por roles, soporte multilenguaje y preparación para integraciones externas (APIs, dashboards).
"""

import logging
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.views.generic import CreateView, DetailView, FormView, ListView, UpdateView

from apps.transacciones.forms import FiltroTransaccionForm, MotivoTransaccionForm, TransaccionForm
from apps.transacciones.models import MotivoTransaccion, Transaccion, ESTADO_TRANSACCION_CHOICES
from apps.transacciones.services import (
    asignar_saldo,
    devolver_saldo_por_error,
    TransaccionService,
)

from apps.vendedores.models import DistribuidorVendedor

# Configuración del logger para auditoría profesional
logger = logging.getLogger(__name__)

# ============================
# 🔹 VALIDACIONES DE ROLES
# ============================

def es_admin(user):
    """Verifica si el usuario es administrador."""
    return user.is_authenticated and user.rol == 'admin'

def es_distribuidor(user):
    """Verifica si el usuario es distribuidor."""
    return user.is_authenticated and user.rol == 'distribuidor'

def es_vendedor(user):
    """Verifica si el usuario es vendedor."""
    return user.is_authenticated and user.rol == 'vendedor'

def tiene_permiso_transacciones(user):
    """Verifica si el usuario tiene permiso para gestionar transacciones."""
    return user.is_authenticated and user.rol in ['admin', 'distribuidor']

def tiene_permiso_motivos(user):
    """Verifica si el usuario tiene permiso para gestionar motivos."""
    return user.is_authenticated and user.rol == 'admin'

# ============================
# 🌐 VISTA INTERNACIONAL - LISTA DE TRANSACCIONES
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_transacciones, login_url='users:login'), name='dispatch')
class ListaTransaccionesView(FormView, ListView):
    """
    Vista avanzada para listar transacciones financieras con filtros, estadísticas y auditoría.
    Diseñada para administradores y distribuidores, optimiza consultas y garantiza seguridad.
    Soporta internacionalización, paginación y preparación para integraciones futuras (e.g., exportación, IA).
    """
    model = Transaccion
    template_name = 'transacciones/listar_transacciones.html'
    form_class = FiltroTransaccionForm
    context_object_name = 'transacciones'
    paginate_by = 25  # 🚀 Paginación ajustable para listas largas

    def get_form_kwargs(self):
        """Pasa los datos de la solicitud y el usuario autenticado al formulario de filtros."""
        kwargs = super().get_form_kwargs()
        kwargs.update({
            'data': self.request.GET,
            'user': self.request.user  # Pasa el usuario autenticado
        })
        return kwargs

    def get_queryset(self):
        """
        Filtra transacciones según el formulario y rol del usuario.
        Optimiza consultas con select_related y prefetch_related.
        """
        user = self.request.user
        form = self.get_form()
        queryset = Transaccion.objects.select_related(
            'moneda', 'emisor', 'receptor', 'motivo', 'realizado_por'
        ).prefetch_related('historiales_rel')

        # Restringir transacciones según rol
        if user.rol == 'distribuidor':
            # Buscar la relación DistribuidorVendedor donde el usuario es distribuidor
            distribuidor_vendedores = DistribuidorVendedor.objects.filter(
                distribuidor=user, activo=True
            )
            if not distribuidor_vendedores.exists():
                # 🛡️ Seguridad: Registrar intento de acceso sin relación activa
                logger.warning(
                    f"[{now()}] Distribuidor {user.username} intentó acceder a transacciones sin relación activa "
                    f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                    f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                )
                raise PermissionDenied(_("No tienes una relación activa como distribuidor."))

            vendedores_ids = distribuidor_vendedores.values_list('vendedor_id', flat=True)
            queryset = queryset.filter(
                Q(emisor=user) |
                Q(receptor=user) |
                Q(receptor__id__in=vendedores_ids)
            )
        elif user.rol != 'admin':
            # 🛡️ Seguridad: Bloquear acceso para roles no permitidos
            logger.warning(
                f"[{now()}] Usuario {user.username} con rol {user.rol} intentó acceder a transacciones sin permiso "
                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            raise PermissionDenied(_("No tienes permisos para ver transacciones."))

        # Aplicar filtros del formulario
        if form.is_valid():
            cd = form.cleaned_data
            if cd.get('fecha_inicio'):
                queryset = queryset.filter(fecha_creacion__gte=cd['fecha_inicio'])
            if cd.get('fecha_fin'):
                queryset = queryset.filter(fecha_creacion__lte=cd['fecha_fin'])
            if cd.get('tipo'):
                queryset = queryset.filter(tipo=cd['tipo'])
            if cd.get('estado'):
                queryset = queryset.filter(estado=cd['estado'])
            if cd.get('moneda'):
                queryset = queryset.filter(moneda=cd['moneda'])
            if cd.get('usuario'):
                queryset = queryset.filter(
                    Q(emisor=cd['usuario']) | Q(receptor=cd['usuario'])
                )

        return queryset.order_by('-fecha_creacion')

    def get_context_data(self, **kwargs):
        """
        Añade contexto adicional para la vista, incluyendo estadísticas avanzadas y opciones de filtro.
        """
        context = super().get_context_data(**kwargs)
        context['form'] = self.get_form()
        context['titulo'] = _("Historial de Transacciones")
        context['es_admin'] = es_admin(self.request.user)
        context['es_distribuidor'] = es_distribuidor(self.request.user)

        # Determinar la plantilla base según el rol del usuario
        context['base_template'] = 'base_admin.html' if context['es_admin'] else 'base_distribuidor.html'

        # Estadísticas avanzadas para dashboard
        queryset = self.get_queryset()
        context['total_transacciones'] = queryset.count()
        context['total_monto'] = queryset.aggregate(
            total=Sum('monto')
        )['total'] or Decimal('0.00')

        # Estadísticas por estado
        context['transacciones_exitosa'] = queryset.filter(estado='EXITOSA').count()
        context['transacciones_pendiente'] = queryset.filter(estado='PENDIENTE').count()
        context['transacciones_fallida'] = queryset.filter(estado='FALLIDA').count()
        context['transacciones_cancelada'] = queryset.filter(estado='CANCELADA').count()

        # Estadísticas por tipo
        context['transacciones_asignacion'] = queryset.filter(tipo='ASIGNACION').count()
        context['transacciones_retiro'] = queryset.filter(tipo='RETIRO').count()
        context['transacciones_consumo_api'] = queryset.filter(tipo='CONSUMO_API').count()
        context['transacciones_devolucion'] = queryset.filter(tipo='DEVOLUCION').count()
        context['transacciones_ajuste_manual'] = queryset.filter(tipo='AJUSTE_MANUAL').count()
        context['transacciones_reverso'] = queryset.filter(tipo='REVERSO').count()

        # Añadir choices para los filtros
        context['tipo_choices'] = Transaccion.TIPO_CHOICES
        context['estado_choices'] = ESTADO_TRANSACCION_CHOICES

        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log con información detallada."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} (rol: {request.user.rol}) accedió a la lista de transacciones "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')}, "
            f"Query Params: {request.GET.dict()})"
        )
        return super().dispatch(request, *args, **kwargs)

# ============================
# 🔹 VISTA PARA CREAR TRANSACCIÓN
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_transacciones, login_url='users:login'), name='dispatch')
class TransaccionCreateView(LoginRequiredMixin, CreateView):
    """
    Vista para crear transacciones manuales.
    Utiliza TransaccionService para procesar la lógica financiera con auditoría.
    Valida comentario_reverso para transacciones de tipo REVERSO.
    """
    model = Transaccion
    form_class = TransaccionForm
    template_name = 'transacciones/crear_transaccion.html'
    success_url = reverse_lazy('transacciones:listar')

    def get_form_kwargs(self):
        """Pasa el usuario autenticado al formulario para aplicar filtros correctos."""
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        """Procesa la transacción usando TransaccionService."""
        try:
            with transaction.atomic():
                transaccion = form.save(commit=False)
                transaccion.realizado_por = self.request.user

                # Verificar permisos para distribuidores
                if not es_admin(self.request.user):
                    if es_distribuidor(self.request.user):
                        if transaccion.emisor != self.request.user:
                            logger.warning(
                                f"[{now()}] Distribuidor {self.request.user.username} intentó emitir transacción desde otra cuenta "
                                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                            )
                            messages.error(self.request, _("Solo puedes emitir transacciones desde tu cuenta."))
                            return self.form_invalid(form)
                    else:
                        logger.warning(
                            f"[{now()}] Usuario {self.request.user.username} sin permisos intentó crear transacción "
                            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                        )
                        messages.error(self.request, _("No tienes permisos para realizar esta acción."))
                        return self.form_invalid(form)

                # Validar comentario_reverso para transacciones de tipo REVERSO
                if transaccion.tipo == 'REVERSO':
                    if not transaccion.comentario_reverso or len(transaccion.comentario_reverso.strip()) < 5:
                        logger.warning(
                            f"[{now()}] Comentario de reverso inválido para usuario {self.request.user.username} "
                            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                        )
                        form.add_error('comentario_reverso', _("Debe proporcionar un comentario justificando el reverso (mínimo 5 caracteres)."))
                        return self.form_invalid(form)

                # Usar TransaccionService para procesar la lógica financiera
                servicio = TransaccionService(
                    tipo=transaccion.tipo,
                    monto=transaccion.monto,
                    moneda=transaccion.moneda,
                    emisor=transaccion.emisor,
                    receptor=transaccion.receptor,
                    motivo=transaccion.motivo,
                    descripcion=transaccion.descripcion,
                    comentario_reverso=transaccion.comentario_reverso if transaccion.tipo == 'REVERSO' else None,
                    tasa_cambio=transaccion.tasa_cambio,
                    referencia_externa=transaccion.referencia_externa,
                    realizado_por=self.request.user
                )
                transaccion = servicio.procesar()
                messages.success(self.request, _("✅ Transacción registrada exitosamente."))
                logger.info(
                    f"[{now()}] Transacción creada por {self.request.user.username}: "
                    f"{transaccion.tipo} {transaccion.monto} {transaccion.moneda.codigo} "
                    f"(UUID: {transaccion.uuid}) "
                    f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                    f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                )
                return self.redirect(self.get_success_url())
        except ValidationError as e:
            messages.error(self.request, str(e))
            logger.error(
                f"[{now()}] Error al crear transacción por {self.request.user.username}: {str(e)} "
                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, _("Error inesperado al procesar la transacción: ") + str(e))
            logger.error(
                f"[{now()}] Error inesperado al crear transacción por {self.request.user.username}: {str(e)} "
                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Maneja errores de formulario."""
        messages.error(self.request, _("Por favor corrija los errores del formulario."))
        logger.warning(
            f"[{now()}] Formulario de transacción inválido para {self.request.user.username} "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Añade contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['titulo'] = _("Crear Nueva Transacción")
        context['base_template'] = 'base_admin.html' if es_admin(self.request.user) else 'base_distribuidor.html'
        try:
            context['saldo_disponible'] = f"{self.request.user.perfil_distribuidor_rel.saldo_actual:.2f} {self.request.user.perfil_distribuidor_rel.moneda}"
        except AttributeError:
            context['saldo_disponible'] = _("No disponible")
        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} accedió a crear una transacción "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().dispatch(request, *args, **kwargs)

# ============================
# 🔹 VISTA PARA LISTA DE MOTIVOS
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_motivos, login_url='users:login'), name='dispatch')
class MotivoTransaccionListView(ListView):
    """
    Vista para listar motivos de transacción.
    Restringida a administradores, con ordenación por estado activo y código.
    """
    model = MotivoTransaccion
    template_name = 'transacciones/motivos/listar_motivos.html'
    context_object_name = 'motivos'
    queryset = MotivoTransaccion.objects.all().order_by('-activo', 'codigo')
    paginate_by = 25

    def get_context_data(self, **kwargs):
        """Añade contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['titulo'] = _("Motivos de Transacción")
        context['base_template'] = 'base_admin.html' if es_admin(self.request.user) else 'base_distribuidor.html'
        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} accedió a la lista de motivos "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().dispatch(request, *args, **kwargs)

# ============================
# 🔹 VISTA PARA CREAR MOTIVO
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_motivos, login_url='users:login'), name='dispatch')
class MotivoTransaccionCreateView(CreateView):
    """
    Vista para crear nuevos motivos de transacción.
    Restringida a administradores, con auditoría de creación.
    """
    model = MotivoTransaccion
    form_class = MotivoTransaccionForm
    template_name = 'transacciones/motivos/crear_motivo.html'
    success_url = reverse_lazy('transacciones:motivos')

    def form_valid(self, form):
        """Guarda el motivo y registra la acción."""
        try:
            with transaction.atomic():
                motivo = form.save()
                messages.success(self.request, _("Motivo de transacción creado correctamente."))
                logger.info(
                    f"[{now()}] Motivo creado por {self.request.user.username}: "
                    f"{motivo.codigo} - {motivo.descripcion} "
                    f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                    f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                )
                return redirect(self.get_success_url())
        except Exception as e:
            messages.error(self.request, _("Error al crear el motivo: ") + str(e))
            logger.error(
                f"[{now()}] Error al crear motivo por {self.request.user.username}: {str(e)} "
                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Maneja errores de formulario."""
        messages.error(self.request, _("Por favor corrija los errores del formulario."))
        logger.warning(
            f"[{now()}] Formulario de motivo inválido para {self.request.user.username} "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Añade contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['titulo'] = _("Crear Nuevo Motivo")
        context['base_template'] = 'base_admin.html' if es_admin(self.request.user) else 'base_distribuidor.html'
        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} accedió a crear un motivo "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().dispatch(request, *args, **kwargs)

# ============================
# 🔹 VISTA PARA ACTUALIZAR MOTIVO
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_motivos, login_url='users:login'), name='dispatch')
class MotivoTransaccionUpdateView(UpdateView):
    """
    Vista para actualizar motivos de transacción existentes.
    Restringida a administradores, con auditoría de actualización.
    """
    model = MotivoTransaccion
    form_class = MotivoTransaccionForm
    template_name = 'transacciones/motivos/editar_motivo.html'
    success_url = reverse_lazy('transacciones:motivos')

    def get_object(self, queryset=None):
        """Obtiene el motivo con verificación de permisos."""
        motivo = super().get_object(queryset)
        return motivo

    def form_valid(self, form):
        """Guarda el motivo actualizado y registra la acción."""
        try:
            with transaction.atomic():
                motivo = form.save()
                messages.success(self.request, _("Motivo de transacción actualizado correctamente."))
                logger.info(
                    f"[{now()}] Motivo actualizado por {self.request.user.username}: "
                    f"{motivo.codigo} - {motivo.descripcion} "
                    f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                    f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
                )
                return redirect(self.get_success_url())
        except Exception as e:
            messages.error(self.request, _("Error al actualizar el motivo: ") + str(e))
            logger.error(
                f"[{now()}] Error al actualizar motivo por {self.request.user.username}: {str(e)} "
                f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
                f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Maneja errores de formulario."""
        messages.error(self.request, _("Por favor corrija los errores del formulario."))
        logger.warning(
            f"[{now()}] Formulario de motivo inválido para {self.request.user.username} "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        """Añade contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['titulo'] = _("Editar Motivo de Transacción")
        context['base_template'] = 'base_admin.html' if es_admin(self.request.user) else 'base_distribuidor.html'
        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} accedió a editar un motivo "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().dispatch(request, *args, **kwargs)

# ============================
# 🔹 VISTA PARA DETALLE DE TRANSACCIÓN
# ============================

@method_decorator(login_required, name='dispatch')
@method_decorator(user_passes_test(tiene_permiso_transacciones, login_url='users:login'), name='dispatch')
class TransaccionDetailView(DetailView):
    """
    Vista para mostrar detalles de una transacción específica.
    Restringe acceso según rol y proporciona auditoría detallada.
    """
    model = Transaccion
    template_name = 'transacciones/detalle_transaccion.html'
    context_object_name = 'transaccion'

    def get_object(self, queryset=None):
        """Obtiene la transacción con verificación de permisos."""
        transaccion = super().get_object(queryset)
        user = self.request.user
        if user.rol == 'admin':
            return transaccion
        if user.rol == 'distribuidor':
            # Buscar la relación DistribuidorVendedor donde el usuario es distribuidor
            distribuidor_vendedores = DistribuidorVendedor.objects.filter(
                distribuidor=user, activo=True
            )
            if not distribuidor_vendedores.exists():
                logger.warning(
                    f"[{now()}] Distribuidor {user.username} intentó acceder al detalle de "
                    f"una transacción sin relación activa."
                )
                raise PermissionDenied(_("No tienes una relación activa como distribuidor."))

            vendedores_ids = distribuidor_vendedores.values_list('vendedor_id', flat=True)
            if (transaccion.emisor == user or
                    transaccion.receptor == user or
                    transaccion.receptor_id in vendedores_ids):
                return transaccion
            raise PermissionDenied(_("No tiene permiso para ver esta transacción."))
        raise PermissionDenied(_("No tiene permiso para ver esta transacción."))

    def get_context_data(self, **kwargs):
        """Añade contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['titulo'] = _("Detalles de la Transacción")
        context['historial_saldo'] = self.object.historiales_rel.select_related('usuario')
        context['auditorias'] = self.object.auditorias_rel.select_related('usuario').order_by('-fecha')
        context['base_template'] = 'base_admin.html' if es_admin(self.request.user) else 'base_distribuidor.html'
        return context

    def dispatch(self, request, *args, **kwargs):
        """Registra la acción en el log."""
        logger.info(
            f"[{now()}] Usuario {request.user.username} accedió al detalle de una transacción "
            f"(IP: {self.request.META.get('REMOTE_ADDR', 'N/A')}, "
            f"User-Agent: {self.request.META.get('HTTP_USER_AGENT', 'N/A')})"
        )
        return super().dispatch(request, *args, **kwargs)


        