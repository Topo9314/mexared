"""
Vistas para el módulo de Líneas en MexaRed.
Proporcionan endpoints REST y vistas web para gestionar líneas telefónicas (SIMs).
Diseñadas para entornos SaaS multinivel con jerarquías (Admin, Distribuidor, Vendedor).
Soportan permisos jerárquicos, auditoría, internacionalización y están preparadas para integración con Addinteli API.
Cumplen con estándares internacionales (PCI DSS, SOC2, ISO 27001) para seguridad y escalabilidad.
"""

import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db import models
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DetailView, DeleteView, TemplateView
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from apps.lineas.models import Linea
from apps.lineas.serializers import LineaReadSerializer, LineaCreateSerializer
from apps.lineas.forms import LineaForm
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR

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
            logger.warning(
                f"Intento de acceso no autenticado a {view.__class__.__name__} "
                f"desde {request.META.get('REMOTE_ADDR', 'unknown')}"
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
            f"(rol: {user.rol}) desde {request.META.get('REMOTE_ADDR', 'unknown')}"
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

        if search:
            qs = qs.filter(models.Q(msisdn__icontains=search) | models.Q(iccid__icontains=search))
        if estado:
            qs = qs.filter(estado=estado)
        if distribuidor_id and user.rol == ROLE_ADMIN:
            qs = qs.filter(distribuidor_id=distribuidor_id)
        if categoria_servicio:
            qs = qs.filter(categoria_servicio=categoria_servicio)

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

        logger.info(
            f"Usuario {user.username} (rol: {user.rol}) consultó lista de líneas web"
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
                f"Intento de creación de línea denegado para {request.user.username} (no superusuario)"
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
            f"(ICCID: {form.instance.iccid}, estado: {form.instance.estado})"
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
                f"Intento de edición de línea denegado para {request.user.username} (no superusuario)"
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
            f"(ICCID: {form.instance.iccid}, estado: {form.instance.estado})"
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
            f"(rol: {user.rol})"
        )
        raise PermissionDenied(_("No tienes permiso para ver esta línea."))

    def get(self, request, *args, **kwargs):
        """
        Registra el acceso al detalle en el log.
        """
        instance = self.get_object()
        logger.info(
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó detalle de línea {instance.msisdn}"
        )
        return super().get(request, *args, **kwargs)

class LineaDeleteView(LoginRequiredMixin, DeleteView):
    """
    Vista web para eliminación lógica de líneas (solo para Admins).
    Marca la línea como 'cancelled' y registra auditoría.
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
                f"Intento de eliminación de línea denegado para {request.user.username} (no superusuario)"
            )
            raise PermissionDenied(_("Solo los administradores pueden eliminar líneas."))
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        """
        Realiza eliminación lógica marcando la línea como 'cancelled'.
        """
        obj = self.get_object()
        obj.estado = 'cancelled'
        obj.fecha_baja = timezone.now()
        obj.actualizado_por = request.user
        obj.save()
        logger.info(
            f"Usuario {request.user.username} marcó línea {obj.msisdn} como cancelada "
            f"(ICCID: {obj.iccid})"
        )
        return super().delete(request, *args, **kwargs)

class LineaWebListView(LoginRequiredMixin, TemplateView):
    """
    Vista web para listar líneas según la jerarquía del usuario.
    Admin: Todas las líneas.
    Distribuidor: Líneas asignadas a él.
    Vendedor: Líneas asignadas a él.
    Soporta filtros avanzados, búsqueda y paginación.
    """
    template_name = "lineas/lineas_list.html"

    def get_context_data(self, **kwargs):
        """
        Proporciona el contexto para la plantilla, incluyendo líneas paginadas, filtros y fecha actual.
        """
        context = super().get_context_data(**kwargs)
        user = self.request.user
        now = timezone.now()

        # Base queryset con optimización
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
        expiring_soon = self.request.GET.get('expiring_soon', '')
        expired = self.request.GET.get('expired', '')
        categoria_servicio = self.request.GET.get('categoria_servicio', '')

        if search:
            qs = qs.filter(models.Q(msisdn__icontains=search) | models.Q(iccid__icontains=search))
        if estado:
            qs = qs.filter(estado=estado)
        if distribuidor_id and user.rol == ROLE_ADMIN:
            qs = qs.filter(distribuidor_id=distribuidor_id)
        if expiring_soon == 'true':
            # Líneas próximas a expirar (en los próximos 7 días)
            qs = qs.filter(
                fecha_vencimiento_plan__gte=now,
                fecha_vencimiento_plan__lte=now + timezone.timedelta(days=7),
                estado__in=['assigned', 'processing']
            )
        if expired == 'true':
            # Líneas ya expiradas
            qs = qs.filter(
                fecha_vencimiento_plan__lt=now,
                estado__in=['assigned', 'processing']
            )
        if categoria_servicio:
            qs = qs.filter(categoria_servicio=categoria_servicio)

        # Ordenar por fecha de registro descendente
        qs = qs.order_by('-fecha_registro')

        # Paginación
        paginator = Paginator(qs, 50)
        page = self.request.GET.get('page', 1)
        lines_page = paginator.get_page(page)

        # Calcular días restantes o negativos para cada línea
        for line in lines_page:
            if line.fecha_vencimiento_plan:
                delta = line.fecha_vencimiento_plan - now
                line.dias_restantes = delta.days
            else:
                line.dias_restantes = None

        context['lineas'] = lines_page

        # Filtros adicionales para Admin
        if user.rol == ROLE_ADMIN:
            context['distribuidores'] = User.objects.filter(rol=ROLE_DISTRIBUIDOR).order_by('username')

        # Preservar filtros en la paginación
        context['search'] = search
        context['estado'] = estado
        context['distribuidor'] = distribuidor_id
        context['expiring_soon'] = expiring_soon
        context['expired'] = expired
        context['categoria_servicio'] = categoria_servicio
        context['now'] = now

        logger.info(
            f"Usuario {user.username} (rol: {user.rol}) consultó lista de líneas web "
            f"con filtros: search={search}, estado={estado}, distribuidor={distribuidor_id}, "
            f"expiring_soon={expiring_soon}, expired={expired}, categoria_servicio={categoria_servicio}"
        )
        return context

# Vistas API REST
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
            f"Usuario {user.username} (rol: {user.rol}) intentó acceder a líneas sin permisos"
        )
        return Linea.objects.none()

    def get(self, request, *args, **kwargs):
        """
        Registra el acceso a la lista de líneas en el log.
        """
        logger.info(
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó lista de líneas API"
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
            f"Usuario {request.user.username} (rol: {request.user.rol}) consultó detalle de línea {instance.msisdn}"
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
            f"(ICCID: {instance.iccid}, estado: {instance.estado})"
        )

    def create(self, request, *args, **kwargs):
        """
        Maneja la creación con auditoría y manejo de excepciones.
        """
        try:
            return super().create(request, *args, **kwargs)
        except Exception as e:
            logger.error(
                f"Error al crear línea por {request.user.username}: {str(e)}",
                exc_info=True
            )
            raise PermissionDenied(_("Error al crear la línea: ") + str(e))