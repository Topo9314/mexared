"""
Vistas para la gestión de vendedores en MexaRed.
Proporciona listado, creación, asignación/descuento de saldo, y activación/desactivación de vendedores.
Integra el saldo financiero real desde el módulo wallet para el listado.
Incluye auditoría avanzada, optimización de consultas, y soporte multilenguaje.
Cumple con estándares internacionales (PCI DSS, SOC2, ISO 27001) y escalabilidad SaaS.
"""

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import ListView, CreateView, FormView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_cookie
from django.contrib.auth import get_user_model
from django.db import models
from decimal import Decimal
import logging
import uuid
import re

from apps.vendedores.models import DistribuidorVendedor
from apps.vendedores.forms import CrearVendedorForm, AsignarSaldoForm, DescontarSaldoForm, DistribuidorVendedorForm
from apps.wallet.models import Wallet

# Configurar logger para auditoría profesional
logger = logging.getLogger('apps.vendedores')

User = get_user_model()

class DistribuidorRequiredMixin(LoginRequiredMixin):
    """
    Mixin para restringir acceso a usuarios con rol 'distribuidor'.
    Incluye verificación de permisos y soporte para multi-tenant.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            logger.warning(f"Intento de acceso no autenticado a {request.path}")
            return self.handle_no_permission()
        if request.user.rol != 'distribuidor':
            logger.warning(f"Acceso denegado para usuario {request.user.username} con rol {request.user.rol}")
            raise PermissionDenied(_("Acceso restringido a distribuidores."))
        return super().dispatch(request, *args, **kwargs)

class DistribuidorVendedorListView(DistribuidorRequiredMixin, ListView):
    """
    Vista para listar todos los vendedores asignados a un distribuidor.
    Muestra el saldo real (wallet.balance) de cada vendedor, optimizado para evitar N+1 queries.
    Incluye analíticas avanzadas y caching para grandes volúmenes.
    """
    model = DistribuidorVendedor
    template_name = 'vendedores/lista.html'
    context_object_name = 'relaciones'
    paginate_by = 25

    @method_decorator(cache_page(60 * 5, key_prefix='vendedores_list_{{user.pk}}'))
    @method_decorator(vary_on_cookie)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def get_queryset(self):
        """
        Filtra relaciones por distribuidor con consultas optimizadas.
        Incluye wallet.balance mediante select_related para evitar N+1 queries.
        """
        return (
            DistribuidorVendedor.objects.filter(
                distribuidor=self.request.user,
                activo=True
            )
            .select_related('vendedor', 'vendedor__wallet', 'creado_por')
            .prefetch_related('change_logs')
            .order_by('-fecha_creacion')
        )

    def get_context_data(self, **kwargs):
        """
        Añade analíticas y estadísticas al contexto, incluyendo saldo total disponible.
        Usa caching para mejorar rendimiento en entornos de alta carga.
        """
        context = super().get_context_data(**kwargs)
        queryset = self.get_queryset()

        total_vendedores = queryset.count()
        vendedores_activos = queryset.filter(activo=True).count()
        saldo_total = queryset.aggregate(
            total_saldo=models.Sum('saldo_disponible', output_field=models.DecimalField())
        )['total_saldo'] or Decimal('0.00')

        cache_key = f'vendedores_analytics_{self.request.user.pk}'
        analytics = cache.get(cache_key)
        if not analytics:
            analytics = {
                'ultima_creacion': queryset.first().fecha_creacion if total_vendedores > 0 else None,
                'total_saldo': saldo_total,
                'vendedores_activos_porcentaje': (
                    (vendedores_activos / total_vendedores * 100) if total_vendedores > 0 else 0
                ),
            }
            cache.set(cache_key, analytics, timeout=60 * 10)

        context.update({
            'title': _("Lista de Vendedores"),
            'total_vendedores': total_vendedores,
            'vendedores_activos': vendedores_activos,
            'analytics': analytics,
        })
        return context

class DistribuidorVendedorCreateView(DistribuidorRequiredMixin, CreateView):
    """
    Vista para crear un nuevo usuario vendedor y su relación con el distribuidor.
    Soporta creación de usuario, contacto, auditoría y envío de correo de bienvenida.
    Saldo inicial se inicializa a 0.00, y las modificaciones de saldo se gestionan vía transacciones.
    """
    model = User
    form_class = CrearVendedorForm
    template_name = 'vendedores/formulario.html'
    success_url = reverse_lazy('vendedores:lista')

    def get_form_kwargs(self):
        """Pasa el distribuidor autenticado al formulario."""
        kwargs = super().get_form_kwargs()
        kwargs['distribuidor'] = self.request.user
        return kwargs

    def form_valid(self, form):
        """Crea un usuario vendedor y la relación en una transacción segura."""
        try:
            with transaction.atomic():
                user = form.save(commit=False)
                user.rol = 'vendedor'
                user.save()

                relacion = DistribuidorVendedor.objects.create(
                    distribuidor=self.request.user,
                    vendedor=user,
                    saldo_inicial=Decimal('0.00'),
                    saldo_asignado=Decimal('0.00'),
                    saldo_disponible=Decimal('0.00'),
                    moneda='MXN',
                    direccion_contacto=form.cleaned_data.get('direccion', ''),
                    telefono_contacto=form.cleaned_data.get('telefono', ''),
                    correo_contacto=form.cleaned_data.get('email_contacto', ''),
                    nombre_comercial=form.cleaned_data.get('nombre_comercial', f"{user.first_name} {user.last_name}".strip()),
                    es_creado_directamente=True,
                    creado_por=self.request.user,
                    activo=True
                )

                try:
                    self.send_welcome_email(user, form.cleaned_data['password1'])
                except Exception as email_error:
                    logger.warning(f"No se pudo enviar el correo de bienvenida a {user.email}: {str(email_error)}")
                    messages.warning(self.request, _("Vendedor creado, pero no se pudo enviar el correo de bienvenida."))

                logger.info(f"Vendedor {user.username} creado por distribuidor {self.request.user.username} con relación {relacion.pk}")
                messages.success(self.request, _("Vendedor creado y asignado correctamente."))
                return redirect(self.success_url)
        except ValidationError as e:
            logger.error(f"Error de validación al crear vendedor: {str(e)}")
            messages.error(self.request, _("Error al crear el vendedor: ") + str(e))
            return self.form_invalid(form)
        except Exception as e:
            logger.error(f"Error inesperado al crear vendedor: {str(e)}")
            messages.error(self.request, _("Error inesperado: ") + str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Maneja errores de formulario con mensajes claros."""
        messages.error(self.request, _("Por favor corrige los errores en el formulario."))
        return super().form_invalid(form)

    def send_welcome_email(self, user, password):
        """Envía un correo de bienvenida al nuevo vendedor con credenciales."""
        if not user.email:
            raise ValueError(_("El usuario no tiene un correo electrónico válido."))
        
        subject = _("Bienvenido a MexaRed - Credenciales de Acceso")
        context = {
            'user': user,
            'password': password,
            'site_name': "MexaRed",
            'login_url': self.request.build_absolute_uri(reverse_lazy('users:login')),
            'distribuidor': self.request.user.full_name,
            'support_email': settings.SUPPORT_EMAIL or settings.DEFAULT_FROM_EMAIL,
        }
        
        try:
            message = render_to_string('vendedores/emails/welcome_email.txt', context)
            html_message = render_to_string('vendedores/emails/welcome_email.html', context)
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                html_message=html_message,
                fail_silently=False
            )
            logger.info(f"Correo de bienvenida enviado a {user.email}")
        except Exception as e:
            logger.error(f"Error al enviar correo a {user.email}: {str(e)}")
            raise

    def get_context_data(self, **kwargs):
        """Añade título y contexto adicional."""
        context = super().get_context_data(**kwargs)
        context['title'] = _("Crear Nuevo Vendedor")
        context['form_id'] = f"create-vendedor-{uuid.uuid4().hex[:8]}"
        return context

class AsignarSaldoView(DistribuidorRequiredMixin, FormView):
    """
    Vista para asignar saldo adicional a un vendedor.
    Incluye validaciones avanzadas y auditoría automática.
    """
    form_class = AsignarSaldoForm
    template_name = 'vendedores/formulario_asignar.html'

    def dispatch(self, request, *args, **kwargs):
        self.relacion = get_object_or_404(
            DistribuidorVendedor.objects.select_related('vendedor', 'distribuidor'),
            pk=kwargs['pk']
        )
        if self.relacion.distribuidor != request.user:
            logger.warning(f"Intento de acceso no autorizado por {request.user.username} a relación {self.relacion.pk}")
            raise PermissionDenied(_("No tienes permiso para asignar saldo a este vendedor."))
        if not self.relacion.activo:
            messages.error(request, _("No puedes asignar saldo a un vendedor inactivo."))
            return redirect('vendedores:lista')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['relacion'] = self.relacion
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                monto = form.cleaned_data['monto']
                self.relacion.asignar_saldo(
                    monto=monto,
                    moneda='MXN',
                    changed_by=self.request.user
                )
                logger.info(
                    f"Saldo {monto} MXN asignado a vendedor "
                    f"{self.relacion.vendedor.username} por {self.request.user.username}"
                )
                messages.success(self.request, _("Saldo asignado exitosamente."))
                return redirect('vendedores:lista')
        except (ValueError, ValidationError) as e:
            logger.error(f"Error al asignar saldo: {str(e)}")
            messages.error(self.request, str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Por favor corrige los errores en el formulario."))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _("Asignar Saldo a ") + self.relacion.vendedor.full_name
        context['relacion'] = self.relacion
        context['form_id'] = f"asignar-saldo-{uuid.uuid4().hex[:8]}"
        return context

class DescontarSaldoView(DistribuidorRequiredMixin, FormView):
    """
    Vista para descontar saldo disponible de un vendedor.
    Incluye validaciones avanzadas y auditoría automática.
    """
    form_class = DescontarSaldoForm
    template_name = 'vendedores/formulario_descontar.html'

    def dispatch(self, request, *args, **kwargs):
        self.relacion = get_object_or_404(
            DistribuidorVendedor.objects.select_related('vendedor', 'distribuidor'),
            pk=kwargs['pk']
        )
        if self.relacion.distribuidor != request.user:
            logger.warning(f"Intento de acceso no autorizado por {request.user.username} a relación {self.relacion.pk}")
            raise PermissionDenied(_("No tienes permiso para descontar saldo de este vendedor."))
        if not self.relacion.activo:
            messages.error(request, _("No puedes descontar saldo de un vendedor inactivo."))
            return redirect('vendedores:lista')
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['relacion'] = self.relacion
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                monto = form.cleaned_data['monto']
                self.relacion.descontar_saldo(
                    monto=monto,
                    moneda='MXN',
                    changed_by=self.request.user
                )
                logger.info(
                    f"Saldo {monto} MXN descontado de vendedor "
                    f"{self.relacion.vendedor.username} por {self.request.user.username}"
                )
                messages.success(self.request, _("Saldo descontado exitosamente."))
                return redirect('vendedores:lista')
        except (ValueError, ValidationError) as e:
            logger.error(f"Error al descontar saldo: {str(e)}")
            messages.error(self.request, str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Por favor corrige los errores en el formulario."))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _("Descontar Saldo de ") + self.relacion.vendedor.full_name
        context['relacion'] = self.relacion
        context['form_id'] = f"descontar-saldo-{uuid.uuid4().hex[:8]}"
        return context

class DistribuidorVendedorToggleActiveView(DistribuidorRequiredMixin, UpdateView):
    """
    Vista para activar o desactivar un vendedor.
    Registra la acción en el log de auditoría.
    """
    model = DistribuidorVendedor
    fields = ['activo']
    template_name = 'vendedores/toggle_active.html'

    def dispatch(self, request, *args, **kwargs):
        self.relacion = get_object_or_404(
            DistribuidorVendedor.objects.select_related('vendedor', 'distribuidor'),
            pk=kwargs['pk']
        )
        if self.relacion.distribuidor != request.user:
            logger.warning(f"Intento de acceso no autorizado por {request.user.username} a relación {self.relacion.pk}")
            raise PermissionDenied(_("No tienes permiso para modificar este vendedor."))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            with transaction.atomic():
                action = 'desactivado' if self.relacion.activo else 'reactivado'
                if self.relacion.activo:
                    self.relacion.desactivar(changed_by=self.request.user)
                    messages.success(self.request, _("Vendedor desactivado correctamente."))
                else:
                    self.relacion.reactivar(changed_by=self.request.user)
                    messages.success(self.request, _("Vendedor reactivado correctamente."))
                logger.info(
                    f"Vendedor {self.relacion.vendedor.username} {action} por {self.request.user.username}"
                )
                return redirect('vendedores:lista')
        except (ValueError, ValidationError) as e:
            logger.error(f"Error al cambiar estado del vendedor: {str(e)}")
            messages.error(self.request, str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Por favor corrige los errores en el formulario."))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _("Cambiar Estado de ") + self.relacion.vendedor.full_name
        context['relacion'] = self.relacion
        context['action'] = _("Desactivar") if self.relacion.activo else _("Reactivar")
        context['form_id'] = f"toggle-active-{uuid.uuid4().hex[:8]}"
        return context

class DistribuidorVendedorUpdateView(DistribuidorRequiredMixin, UpdateView):
    """
    Vista para editar una relación distribuidor-vendedor existente.
    Permite actualizar datos de contacto (dirección y teléfono).
    Saldo se gestionan exclusivamente a través del módulo de transacciones.
    """
    model = DistribuidorVendedor
    form_class = DistribuidorVendedorForm
    template_name = 'vendedores/formulario_editar.html'
    success_url = reverse_lazy('vendedores:lista')

    def get_queryset(self):
        return DistribuidorVendedor.objects.filter(
            distribuidor=self.request.user
        ).select_related('vendedor', 'distribuidor')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['distribuidor'] = self.request.user
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                instance = form.save(commit=False)
                instance.save()
                logger.info(
                    f"Relación {instance.pk} actualizada por {self.request.user.username}"
                )
                messages.success(self.request, _("Datos actualizados correctamente."))
                return redirect(self.success_url)
        except ValidationError as e:
            logger.error(f"Error al actualizar relación: {str(e)}")
            messages.error(self.request, str(e))
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, _("Hubo un error al actualizar los datos."))
        return super().form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = _("Editar Vendedor ") + self.object.vendedor.full_name
        context['boton'] = _("Actualizar")
        context['form_id'] = f"edit-vendedor-{uuid.uuid4().hex[:8]}"
        return context