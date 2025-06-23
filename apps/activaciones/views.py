# apps/activaciones/views.py
import json
import logging
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import gettext_lazy as _
from django.core.cache import cache
from django.conf import settings
from django.utils import translation
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action
from rest_framework.throttling import UserRateThrottle
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR
from apps.vendedores.models import DistribuidorVendedor
from apps.ofertas.models import Oferta, MargenDistribuidor
from .models import Activacion, AuditLog, PortabilidadDetalle
from .serializers import ActivacionSerializer, ActivacionResponseSerializer, PortabilidadDetalleSerializer
from .forms import FormularioActivacion
from .services import ActivacionService
from django.db.models import Q


# Configuración de logging para auditoría
logger = logging.getLogger(__name__)

class CustomUserRateThrottle(UserRateThrottle):
    """
    Throttle personalizado para limitar tasas por rol de usuario.
    """
    def get_rate(self):
        user = self.request.user if hasattr(self, 'request') else None
        if user and user.rol == ROLE_ADMIN:
            return '200/hour'  # Mayor límite para Admin
        return '100/hour'  # Distribuidores y vendedores

class LargeResultsSetPagination(PageNumberPagination):
    """
    Paginación personalizada para exportaciones grandes.
    """
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 1000

class ActivacionViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar activaciones vía API.
    Soporta creación, listado, detalle y acciones personalizadas, con control por roles.
    Incluye auditoría avanzada, soporte multi-idioma, multi-SIM, y cacheo.
    """
    queryset = Activacion.objects.all().select_related(
        'usuario_solicita', 'distribuidor_asignado', 'oferta'
    ).prefetch_related('portabilidad_detalle')
    serializer_class = ActivacionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = {
        'estado': ['exact'],
        'tipo_activacion': ['exact'],
        'tipo_producto': ['exact'],
        'fecha_solicitud': ['gte', 'lte'],
    }
    throttle_classes = [CustomUserRateThrottle]

    def get_serializer_class(self):
        """
        Usa un serializador diferente para lectura vs escritura.
        """
        if self.action in ['list', 'retrieve', 'detalle_portabilidad', 'exportar_activaciones']:
            return ActivacionResponseSerializer
        return ActivacionSerializer

    def get_queryset(self):
        """
        Filtra las activaciones según el rol del usuario autenticado:
        - Admin: ve todas las activaciones.
        - Distribuidor: ve sus activaciones y las de sus vendedores.
        - Vendedor: ve solo sus activaciones.
        """
        user = self.request.user
        cache_key = f"activaciones_queryset_{user.id}_{user.rol}_{translation.get_language()}"
        cached_queryset = cache.get(cache_key)

        if cached_queryset is not None:
            logger.debug(f"Cache hit for queryset: {cache_key}")
            return cached_queryset

        if not user.is_authenticated:
            logger.warning("Intento de acceso no autenticado a activaciones")
            raise PermissionDenied(_("Debe estar autenticado para acceder a las activaciones."))

        if user.rol == ROLE_ADMIN:
            queryset = self.queryset
        elif user.rol == ROLE_DISTRIBUIDOR:
            vendedor_ids = DistribuidorVendedor.objects.filter(
                distribuidor=user
            ).values_list('vendedor__id', flat=True)
            queryset = self.queryset.filter(
                Q(distribuidor_asignado=user) | Q(usuario_solicita=user) |
                Q(usuario_solicita__id__in=vendedor_ids)
            )
        elif user.rol == ROLE_VENDEDOR:
            queryset = self.queryset.filter(usuario_solicita=user)
        else:
            logger.error(f"Usuario {user.username} con rol no permitido: {user.rol}")
            raise PermissionDenied(_("No tiene permisos para ver estas activaciones."))

        # Cachear el queryset por 5 minutos
        cache.set(cache_key, queryset, timeout=300)
        logger.debug(f"Cache set for queryset: {cache_key}")
        return queryset

    def perform_create(self, serializer):
        """
        Ejecuta la creación de una activación, integrando con el servicio de activaciones.
        Valida permisos de distribuidor y asigna distribuidor_asignado automáticamente.
        Registra auditoría avanzada con IP y detalles del cliente.
        """
        user = self.request.user
        client_ip = self.request.META.get('REMOTE_ADDR', 'unknown')

        if user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
            logger.error(f"Usuario {user.username} con rol {user.rol} intentó crear activación")
            raise PermissionDenied(_("Solo Admin, Distribuidores o Vendedores pueden crear activaciones."))

        # Asignar distribuidor_asignado según el rol
        validated_data = serializer.validated_data
        if user.rol == ROLE_DISTRIBUIDOR:
            validated_data['distribuidor_asignado'] = user
        elif user.rol == ROLE_VENDEDOR:
            try:
                distribuidor_vendedor = DistribuidorVendedor.objects.get(vendedor=user)
                validated_data['distribuidor_asignado'] = distribuidor_vendedor.distribuidor
            except DistribuidorVendedor.DoesNotExist:
                logger.error(f"Vendedor {user.username} no está asociado a ningún distribuidor")
                raise ValidationError(_("El vendedor no está asociado a un distribuidor."))

        # Validar idioma del usuario
        self._set_user_language(user)

        # Guardar activación con datos validados
        validated_data['usuario_solicita'] = user
        activacion = serializer.save(**validated_data)

        # Procesar activación con el servicio
        try:
            service = ActivacionService()
            result = service.procesar_activacion(activacion)
            self.activacion_result = result['activacion']
        except Exception as e:
            logger.error(
                f"Error procesando activación ID={activacion.id}: {str(e)}",
                exc_info=True
            )
            raise ValidationError(_("Error al procesar la activación: ") + str(e))

        # Generar detalles de auditoría
        audit_details = {
            'iccid': activacion.iccid,
            'tipo_activacion': activacion.tipo_activacion,
            'distribuidor_asignado': str(activacion.distribuidor_asignado.id) if activacion.distribuidor_asignado else None,
            'client_ip': client_ip,
            'user_agent': self.request.META.get('HTTP_USER_AGENT', 'unknown')
        }

        # Registrar auditoría avanzada
        AuditLog.objects.create(
            usuario=user,
            accion='CREAR_ACTIVACION',
            entidad='Activacion',
            entidad_id=str(activacion.id),
            detalles=audit_details,
            ip_address=client_ip
        )

        logger.info(
            f"Activación creada: ID={activacion.id}, ICCID={activacion.iccid}, "
            f"Usuario={user.username}, Rol={user.rol}, IP={client_ip}"
        )

    def create(self, request, *args, **kwargs):
        """
        Crea una activación con respuesta personalizada.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        response_serializer = ActivacionResponseSerializer(self.activacion_result)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

    def list(self, request, *args, **kwargs):
        """
        Lista activaciones filtradas por rol, con soporte para filtros avanzados y cacheo.
        """
        user = self.request.user
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        serializer = self.get_serializer(page or queryset, many=True)

        # Registrar auditoría de consulta
        audit_details = {
            'filtros': request.query_params.dict(),
            'client_ip': request.META.get('REMOTE_ADDR', 'unknown'),
            'count': queryset.count()
        }
        AuditLog.objects.create(
            usuario=user,
            accion='LISTAR_ACTIVACIONES',
            entidad='Activacion',
            entidad_id=None,
            detalles=audit_details,
            ip_address=request.META.get('REMOTE_ADDR', 'unknown')
        )

        return self.get_paginated_response(serializer.data) if page else Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """
        Obtiene detalles de una activación específica.
        """
        user = self.request.user
        instance = self.get_object()
        serializer = self.get_serializer(instance)

        # Registrar auditoría de detalle
        audit_details = {
            'iccid': instance.iccid,
            'client_ip': request.META.get('REMOTE_ADDR', 'unknown')
        }
        AuditLog.objects.create(
            usuario=user,
            accion='VER_ACTIVACION',
            entidad='Activacion',
            entidad_id=str(instance.id),
            detalles=audit_details,
            ip_address=request.META.get('REMOTE_ADDR', 'unknown')
        )

        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='detalle-portabilidad')
    def detalle_portabilidad(self, request, pk=None):
        """
        Acción personalizada: obtiene los datos de portabilidad de una activación.
        """
        user = self.request.user
        activacion = self.get_object()
        audit_details = {
            'iccid': activacion.iccid,
            'portabilidad': 'No disponible' if not activacion.portabilidad_detalle else 'Disponible',
            'client_ip': request.META.get('REMOTE_ADDR', 'unknown')
        }

        # Registrar auditoría de consulta de portabilidad
        AuditLog.objects.create(
            usuario=user,
            accion='VER_PORTABILIDAD',
            entidad='Activacion',
            entidad_id=str(activacion.id),
            detalles=audit_details,
            ip_address=request.META.get('REMOTE_ADDR', 'unknown')
        )

        if activacion.portabilidad_detalle:
            serializer = PortabilidadDetalleSerializer(activacion.portabilidad_detalle)
            return Response({'portabilidad': serializer.data})
        return Response({'portabilidad': None}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='exportar-activaciones', pagination_class=LargeResultsSetPagination)
    def exportar_activaciones(self, request):
        """
        Acción personalizada: exporta activaciones filtradas con paginación.
        Soporta JSON, con preparación para CSV/Excel en el futuro.
        """
        user = self.request.user
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            response_data = self.get_paginated_response(serializer.data).data
        else:
            serializer = self.get_serializer(queryset, many=True)
            response_data = {
                'export_type': 'json',
                'data': serializer.data,
                'count': queryset.count()
            }

        # Registrar auditoría de exportación
        audit_details = {
            'filtros': request.query_params.dict(),
            'client_ip': request.META.get('REMOTE_ADDR', 'unknown'),
            'export_type': 'json',
            'count': queryset.count()
        }
        AuditLog.objects.create(
            usuario=user,
            accion='EXPORTAR_ACTIVACIONES',
            entidad='Activacion',
            entidad_id=None,
            detalles=audit_details,
            ip_address=request.META.get('REMOTE_ADDR', 'unknown')
        )

        return Response(response_data)

    def destroy(self, request, *args, **kwargs):
        """
        Deshabilita eliminación de activaciones para garantizar trazabilidad.
        """
        logger.warning(f"Intento de eliminación de activación por usuario {request.user.username}")
        raise PermissionDenied(_("La eliminación de activaciones no está permitida."))

    def _set_user_language(self, user: User) -> None:
        """
        Establece el idioma del usuario según su perfil o cabecera Accept-Language.
        """
        user_language = getattr(user, 'preferred_language', settings.LANGUAGE_CODE)
        accept_language = self.request.META.get('HTTP_ACCEPT_LANGUAGE', '').split(',')[0].split('-')[0]
        language = accept_language if accept_language in [l[0] for l in settings.LANGUAGES] else user_language
        translation.activate(language)
        logger.debug(f"Idioma activado para usuario {user.username}: {language}")

@login_required
def listado_activaciones_html(request):
    """
    Vista HTML para el listado de activaciones.
    Soporta filtros por ICCID, estado, tipo de producto y rango de fechas.
    Incluye paginación y auditoría para trazabilidad.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    if user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
        logger.error(f"Usuario {user.username} con rol {user.rol} intentó acceder al listado de activaciones")
        raise PermissionDenied(_("Solo Admin, Distribuidores o Vendedores pueden ver el listado de activaciones."))

    # Inicializar queryset base según rol
    if user.rol == ROLE_ADMIN:
        queryset = Activacion.objects.all()
    elif user.rol == ROLE_DISTRIBUIDOR:
        vendedor_ids = DistribuidorVendedor.objects.filter(
            distribuidor=user
        ).values_list('vendedor__id', flat=True)
        queryset = Activacion.objects.filter(
            Q(distribuidor_asignado=user) | Q(usuario_solicita=user) |
            Q(usuario_solicita__id__in=vendedor_ids)
        )
    else:  # ROLE_VENDEDOR
        queryset = Activacion.objects.filter(usuario_solicita=user)

    # Aplicar filtros
    iccid = request.GET.get('iccid')
    estado = request.GET.get('estado')
    tipo_producto = request.GET.get('tipo_producto')
    fecha_solicitud_gte = request.GET.get('fecha_solicitud__gte')
    fecha_solicitud_lte = request.GET.get('fecha_solicitud__lte')

    if iccid:
        queryset = queryset.filter(iccid__icontains=iccid)
    if estado:
        queryset = queryset.filter(estado=estado)
    if tipo_producto:
        queryset = queryset.filter(tipo_producto=tipo_producto)
    if fecha_solicitud_gte:
        queryset = queryset.filter(fecha_solicitud__gte=fecha_solicitud_gte)
    if fecha_solicitud_lte:
        queryset = queryset.filter(fecha_solicitud__lte=fecha_solicitud_lte)

    # Ordenar por fecha de solicitud descendente
    queryset = queryset.select_related('usuario_solicita', 'distribuidor_asignado', 'oferta').order_by('-fecha_solicitud')

    # Paginación
    paginator = Paginator(queryset, 50)  # 50 activaciones por página
    page = request.GET.get('page')
    try:
        activaciones = paginator.page(page)
    except PageNotAnInteger:
        activaciones = paginator.page(1)
    except EmptyPage:
        activaciones = paginator.page(paginator.num_pages)

    # Registrar auditoría
    audit_details = {
        'filtros': request.GET.dict(),
        'client_ip': client_ip,
        'count': queryset.count(),
        'page': page or '1'
    }
    AuditLog.objects.create(
        usuario=user,
        accion='LISTAR_ACTIVACIONES_HTML',
        entidad='Activacion',
        entidad_id=None,
        detalles=audit_details,
        ip_address=client_ip
    )

    logger.info(
        f"Listado de activaciones accedido por usuario {user.username}, "
        f"Rol={user.rol}, IP={client_ip}, Filtros={audit_details['filtros']}"
    )

    context = {
        'activaciones': activaciones,
        'is_paginated': activaciones.has_other_pages(),
        'page_obj': activaciones,
        'querystring': request.GET.urlencode()  # Para preservar filtros en paginación
    }
    return render(request, 'activaciones/listado.html', context)

@login_required
def crear_activacion_html(request):
    """
    Vista HTML para crear una nueva activación.
    Maneja formulario único para activaciones normales y portabilidades.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    if user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
        logger.error(f"Usuario {user.username} con rol {user.rol} intentó crear activación")
        raise PermissionDenied(_("Solo Admin, Distribuidores o Vendedores pueden crear activaciones."))

    if request.method == 'POST':
        form = FormularioActivacion(request.POST, user=user)
        if form.is_valid():
            try:
                activacion = form.save()
                # Registrar auditoría
                audit_details = {
                    'iccid': activacion.iccid,
                    'tipo_activacion': activacion.tipo_activacion,
                    'distribuidor_asignado': str(activacion.distribuidor_asignado.id) if activacion.distribuidor_asignado else None,
                    'client_ip': client_ip,
                    'user_agent': request.META.get('HTTP_USER_AGENT', 'unknown')
                }
                AuditLog.objects.create(
                    usuario=user,
                    accion='CREAR_ACTIVACION_HTML',
                    entidad='Activacion',
                    entidad_id=str(activacion.id),
                    detalles=audit_details,
                    ip_address=client_ip
                )
                logger.info(
                    f"Activación creada (HTML): ID={activacion.id}, ICCID={activacion.iccid}, "
                    f"Usuario={user.username}, Rol={user.rol}, IP={client_ip}"
                )
                return redirect('activaciones:detalle_activacion', pk=activacion.id)
            except ValidationError as e:
                form.add_error(None, str(e))
                logger.error(
                    f"Error creando activación (HTML) para usuario {user.username}: {str(e)}",
                    exc_info=True
                )
    else:
        form = FormularioActivacion(user=user)

    context = {
        'form': form,
        'is_portabilidad': request.GET.get('tipo_activacion') == 'ACTIVACION_PORTABILIDAD'
    }
    return render(request, 'activaciones/crear.html', context)

@login_required
def detalle_activacion(request, pk):
    """
    Vista HTML para mostrar los detalles de una activación específica.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    if user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR]:
        logger.error(f"Usuario {user.username} con rol {user.rol} intentó acceder al detalle de activación {pk}")
        raise PermissionDenied(_("Solo Admin, Distribuidores o Vendedores pueden ver detalles de activaciones."))

    # Filtrar según rol
    if user.rol == ROLE_ADMIN:
        activacion = get_object_or_404(Activacion, id=pk)
    elif user.rol == ROLE_DISTRIBUIDOR:
        vendedor_ids = DistribuidorVendedor.objects.filter(
            distribuidor=user
        ).values_list('vendedor__id', flat=True)
        activacion = get_object_or_404(
            Activacion,
            Q(id=pk) & (Q(distribuidor_asignado=user) | Q(usuario_solicita=user) | Q(usuario_solicita__id__in=vendedor_ids))
        )
    else:  # ROLE_VENDEDOR
        activacion = get_object_or_404(Activacion, id=pk, usuario_solicita=user)

    # Registrar auditoría
    audit_details = {
        'iccid': activacion.iccid,
        'tipo_activacion': activacion.tipo_activacion,
        'client_ip': client_ip,
        'user_agent': request.META.get('HTTP_USER_AGENT', 'unknown')
    }
    AuditLog.objects.create(
        usuario=user,
        accion='VER_ACTIVACION_HTML',
        entidad='Activacion',
        entidad_id=str(activacion.id),
        detalles=audit_details,
        ip_address=client_ip
    )

    logger.info(
        f"Detalle de activación accedido: ID={activacion.id}, ICCID={activacion.iccid}, "
        f"Usuario={user.username}, Rol={user.rol}, IP={client_ip}"
    )

    context = {
        'activacion': activacion,
        'portabilidad_detalle': activacion.portabilidad_detalle if hasattr(activacion, 'portabilidad_detalle') else None
    }
    return render(request, 'activaciones/detalle.html', context)

@login_required
def list_audit_logs_html(request):
    """
    Vista HTML para listar los registros de auditoría.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')

    if user.rol != ROLE_ADMIN:
        logger.error(f"Usuario {user.username} con rol {user.rol} intentó acceder a los logs de auditoría")
        raise PermissionDenied(_("Solo los administradores pueden ver los logs de auditoría."))

    # Aplicar filtros
    accion = request.GET.get('accion')
    entidad = request.GET.get('entidad')
    fecha_gte = request.GET.get('fecha__gte')
    fecha_lte = request.GET.get('fecha__lte')

    queryset = AuditLog.objects.all().select_related('usuario').order_by('-fecha')
    if accion:
        queryset = queryset.filter(accion=accion)
    if entidad:
        queryset = queryset.filter(entidad=entidad)
    if fecha_gte:
        queryset = queryset.filter(fecha__gte=fecha_gte)
    if fecha_lte:
        queryset = queryset.filter(fecha__lte=fecha_lte)

    # Paginación
    paginator = Paginator(queryset, 50)
    page = request.GET.get('page')
    try:
        audit_logs = paginator.page(page)
    except PageNotAnInteger:
        audit_logs = paginator.page(1)
    except EmptyPage:
        audit_logs = paginator.page(paginator.num_pages)

    # Registrar auditoría
    audit_details = {
        'filtros': request.GET.dict(),
        'client_ip': client_ip,
        'count': queryset.count(),
        'page': page or '1'
    }
    AuditLog.objects.create(
        usuario=user,
        accion='LISTAR_AUDITORIA_HTML',
        entidad='AuditLog',
        entidad_id=None,
        detalles=audit_details,
        ip_address=client_ip
    )

    logger.info(
        f"Logs de auditoría accedidos por usuario {user.username}, "
        f"Rol={user.rol}, IP={client_ip}, Filtros={audit_details['filtros']}"
    )

    context = {
        'audit_logs': audit_logs,
        'is_paginated': audit_logs.has_other_pages(),
        'page_obj': audit_logs,
        'querystring': request.GET.urlencode()
    }
    return render(request, 'activaciones/auditoria.html', context)

@login_required
def get_planes_por_tipo(request):
    """
    Vista AJAX para obtener planes según el tipo de oferta seleccionado.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')
    tipo_oferta = request.GET.get('tipo_oferta')
    
    if not tipo_oferta:
        logger.warning(f"Intento de acceso a get_planes_por_tipo sin tipo_oferta por usuario {user.username}")
        return JsonResponse({'error': _('Tipo de oferta es obligatorio.')}, status=400)

    # Cache key para optimizar rendimiento
    cache_key = f"planes_por_tipo_{tipo_oferta}_{user.id}_{user.rol}"
    cached_planes = cache.get(cache_key)
    if cached_planes is not None:
        logger.debug(f"Cache hit for planes: {cache_key}")
        return JsonResponse(cached_planes, safe=False)

    # Validar tipo_oferta
    valid_tipos = [choice[0] for choice in TIPOS_OFERTA]
    if tipo_oferta not in valid_tipos:
        logger.warning(f"Tipo de oferta inválido: {tipo_oferta} por usuario {user.username}")
        return JsonResponse({'error': _('Tipo de oferta inválido.')}, status=400)

    # Obtener queryset optimizado
    queryset = Oferta.objects.filter(
        activo=True,
        categoria_servicio=tipo_oferta.lower()
    ).order_by('nombre')

    if user.rol != ROLE_ADMIN:
        distribuidor = None
        if user.rol == ROLE_DISTRIBUIDOR:
            distribuidor = user
        elif user.rol == ROLE_VENDEDOR:
            try:
                distribuidor = DistribuidorVendedor.objects.get(vendedor=user).distribuidor
            except DistribuidorVendedor.DoesNotExist:
                logger.warning(f"Vendedor {user.username} no tiene distribuidor asignado.")
                return JsonResponse({'error': _('Vendedor no asociado a un distribuidor.')}, status=400)
        
        if distribuidor:
            queryset = queryset.filter(
                margenes_distribuidor__distribuidor=distribuidor,
                margenes_distribuidor__activo=True
            ).distinct()

    # Serializar datos
    planes = [
        {
            'id': plan.id,
            'nombre': plan.nombre,
            'precio_cliente': str(plan.margenes_distribuidor.filter(distribuidor=distribuidor, activo=True).first().precio_cliente) if user.rol != ROLE_ADMIN else str(plan.costo_base),
            'moneda': plan.moneda
        } for plan in queryset
    ]

    # Cachear respuesta por 10 minutos
    cache.set(cache_key, planes, timeout=600)
    logger.debug(f"Cache set for planes: {cache_key}")

    # Registrar auditoría
    audit_details = {
        'tipo_oferta': tipo_oferta,
        'client_ip': client_ip,
        'count': len(planes)
    }
    AuditLog.objects.create(
        usuario=user,
        accion='CONSULTAR_PLANES_POR_TIPO',
        entidad='Oferta',
        entidad_id=None,
        detalles=audit_details,
        ip_address=client_ip
    )

    logger.info(
        f"Planes por tipo consultados: tipo={tipo_oferta}, "
        f"Usuario={user.username}, Rol={user.rol}, IP={client_ip}, Count={len(planes)}"
    )

    return JsonResponse(planes, safe=False)

@login_required
def get_product_type_by_iccid(request):
    """
    Vista AJAX para obtener el tipo de producto según el ICCID.
    """
    user = request.user
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')
    iccid = request.GET.get('iccid')

    if not iccid or not iccid.isdigit() or len(iccid) not in range(19, 23):
        logger.warning(f"ICCID inválido en get_product_type_by_iccid: {iccid} por usuario {user.username}")
        return JsonResponse({'error': _('ICCID inválido.')}, status=400)

    # Cache key para optimizar rendimiento
    cache_key = f"product_type_iccid_{iccid}_{user.id}"
    cached_response = cache.get(cache_key)
    if cached_response is not None:
        logger.debug(f"Cache hit for ICCID product type: {cache_key}")
        return JsonResponse(cached_response)

    try:
        service = ActivacionService()
        response = service.validar_iccid_con_addinteli(iccid)
        product_type = response.get('result', {}).get('product_type', '').upper()
        if product_type in ['MOVILIDAD', 'MIFI', 'HBB']:
            result = {'tipo_oferta': product_type}
            # Cachear respuesta por 1 hora
            cache.set(cache_key, result, timeout=3600)
            logger.debug(f"Cache set for ICCID product type: {cache_key}")

            # Registrar auditoría
            audit_details = {
                'iccid': iccid,
                'tipo_oferta': product_type,
                'client_ip': client_ip
            }
            AuditLog.objects.create(
                usuario=user,
                accion='CONSULTAR_TIPO_POR_ICCID',
                entidad='Activacion',
                entidad_id=None,
                detalles=audit_details,
                ip_address=client_ip
            )

            logger.info(
                f"Tipo de producto consultado para ICCID {iccid}: {product_type}, "
                f"Usuario={user.username}, Rol={user.rol}, IP={client_ip}"
            )
            return JsonResponse(result)
        return JsonResponse({'error': _('Tipo de producto no identificado.')}, status=400)
    except Exception as e:
        logger.error(f"Error validando ICCID {iccid}: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=400)