"""
Servicio especializado para obtener resúmenes financieros de usuarios en MexaRed.
Centraliza la lógica de consulta de saldos, transacciones y estadísticas para dashboards, reportes y APIs.
Diseñado para escalar en entornos internacionales de alto volumen, con enfoque en México.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from django.db.models import Q, Sum, Avg, Count
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.users.models import User
from apps.users.services.auth_service import AuthService
from apps.transacciones.models import Transaccion, HistorialSaldo
from apps.transacciones.services.saldo_service import SaldoService
from apps.transacciones.services.validaciones import Validaciones

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

class ResumenService:
    """
    Servicio para generar resúmenes financieros y estadísticas en MexaRed.
    Proporciona datos para dashboards, reportes y análisis, con soporte para alto volumen y auditoría detallada.
    """

    @staticmethod
    def obtener_resumen_saldo(usuario, max_transacciones=5):
        """
        Retorna el saldo actual y las últimas transacciones relevantes para un usuario.

        Args:
            usuario (User): Usuario autenticado (cliente, vendedor, distribuidor, admin).
            max_transacciones (int): Número máximo de transacciones a retornar (default: 5).

        Returns:
            dict: Diccionario con 'saldo_actual', 'ultimas_transacciones' y metadatos.

        Raises:
            ValidationError: Si el usuario no es válido o hay errores en la consulta.
        """
        try:
            # Validar usuario
            if not AuthService.is_authenticated(usuario) or not AuthService.is_active(usuario):
                logger.error(f"Usuario {usuario.username} no autenticado o inactivo")
                raise ValidationError(_("Usuario no autenticado o inactivo."))

            # Obtener saldo disponible usando SaldoService
            saldo_actual = SaldoService.consultar_saldo(usuario)

            # Obtener transacciones recientes
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario)
            ).select_related('moneda', 'motivo', 'emisor', 'receptor')\
             .only('id', 'tipo', 'monto', 'moneda__codigo', 'motivo__descripcion', 'fecha_creacion', 'estado')\
             .order_by('-fecha_creacion')[:max_transacciones]

            response = {
                "saldo_actual": saldo_actual,
                "ultimas_transacciones": [
                    {
                        "id": t.id,
                        "tipo": t.tipo,
                        "monto": t.monto,
                        "moneda": t.moneda.codigo,
                        "motivo": t.motivo.descripcion if t.motivo else None,
                        "fecha": t.fecha_creacion,
                        "estado": t.estado,
                        "es_ingreso": t.receptor == usuario
                    } for t in transacciones
                ],
                "metadatos": {
                    "total_transacciones": len(transacciones),
                    "timestamp": timezone.now()
                }
            }

            logger.debug(f"[Resumen] Saldo {saldo_actual} y {len(transacciones)} transacciones generadas para {usuario.username}")
            return response

        except ValidationError as ve:
            logger.error(f"Error de validación al generar resumen para {usuario.username}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al generar resumen para {usuario.username}: {str(e)}")
            return {
                "saldo_actual": Decimal('0.00'),
                "ultimas_transacciones": [],
                "metadatos": {
                    "total_transacciones": 0,
                    "timestamp": timezone.now(),
                    "error": str(e)
                }
            }

    @staticmethod
    def resumen_saldo_historico(usuario, fecha_inicio, fecha_fin):
        """
        Resume el historial de saldos para un usuario en un período especificado.

        Args:
            usuario (User): Usuario autenticado.
            fecha_inicio (date): Fecha inicial del período.
            fecha_fin (date): Fecha final del período.

        Returns:
            dict: Resumen con saldo inicial, final, movimientos y estadísticas.

        Raises:
            ValidationError: Si las fechas son inválidas o el usuario no es válido.
        """
        # Validar usuario y fechas
        if not AuthService.is_authenticated(usuario) or not AuthService.is_active(usuario):
            logger.error(f"Usuario {usuario.username} no autenticado o inactivo")
            raise ValidationError(_("Usuario no autenticado o inactivo."))
        Validaciones.validar_rango_fechas(fecha_inicio, fecha_fin)

        try:
            # Obtener historial de saldos
            historial = HistorialSaldo.objects.filter(
                usuario=usuario,
                fecha__range=(fecha_inicio, fecha_fin)
            ).select_related('transaccion').only(
                'fecha', 'saldo_antes', 'saldo_despues', 'transaccion__id', 'transaccion__tipo'
            ).order_by('fecha')

            if not historial.exists():
                logger.debug(f"No hay historial de saldo para {usuario.username} entre {fecha_inicio} y {fecha_fin}")
                return {
                    "saldo_inicial": Decimal('0.00'),
                    "saldo_final": SaldoService.consultar_saldo(usuario),
                    "movimientos": [],
                    "estadisticas": {
                        "total_movimientos": 0,
                        "monto_neto": Decimal('0.00')
                    }
                }

            saldo_inicial = historial.first().saldo_antes
            saldo_final = historial.last().saldo_despues
            movimientos = [
                {
                    "fecha": item.fecha,
                    "transaccion_id": item.transaccion.id,
                    "monto": item.saldo_despues - item.saldo_antes,
                    "tipo": item.transaccion.tipo,
                    "saldo_resultante": item.saldo_despues
                } for item in historial
            ]

            monto_neto = sum(m['monto'] for m in movimientos)
            response = {
                "saldo_inicial": saldo_inicial,
                "saldo_final": saldo_final,
                "movimientos": movimientos,
                "estadisticas": {
                    "total_movimientos": len(movimientos),
                    "monto_neto": monto_neto
                }
            }

            logger.debug(f"[Histórico] Resumen generado para {usuario.username}: {len(movimientos)} movimientos")
            return response

        except ValidationError as ve:
            logger.error(f"Error de validación al generar historial para {usuario.username}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al generar historial para {usuario.username}: {str(e)}")
            raise ValidationError(_("Error al generar el resumen histórico."))

    @staticmethod
    def resumen_movimientos_por_periodo(usuario, periodo='mensual', fecha_inicio=None, fecha_fin=None):
        """
        Agrupa movimientos (ingresos, egresos) por período (diario, semanal, mensual).

        Args:
            usuario (User): Usuario autenticado.
            periodo (str): Tipo de período ('diario', 'semanal', 'mensual').
            fecha_inicio (date, optional): Fecha inicial del filtro.
            fecha_fin (date, optional): Fecha final del filtro.

        Returns:
            dict: Resumen de ingresos, egresos y movimientos agrupados.

        Raises:
            ValidationError: Si los parámetros son inválidos.
        """
        # Validar usuario y período
        if not AuthService.is_authenticated(usuario) or not AuthService.is_active(usuario):
            logger.error(f"Usuario {usuario.username} no autenticado o inactivo")
            raise ValidationError(_("Usuario no autenticado o inactivo."))
        if periodo not in ['diario', 'semanal', 'mensual']:
            logger.error(f"Período inválido: {periodo}")
            raise ValidationError(_("Período inválido."))

        # Establecer fechas predeterminadas si no se proporcionan
        if not fecha_inicio or not fecha_fin:
            fecha_fin = timezone.now().date()
            if periodo == 'diario':
                fecha_inicio = fecha_fin - timedelta(days=30)
            elif periodo == 'semanal':
                fecha_inicio = fecha_fin - timedelta(weeks=4)
            else:  # mensual
                fecha_inicio = fecha_fin - timedelta(days=365)
        Validaciones.validar_rango_fechas(fecha_inicio, fecha_fin)

        try:
            # Obtener transacciones
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario),
                fecha_creacion__range=(fecha_inicio, fecha_fin)
            ).select_related('moneda').only(
                'fecha_creacion', 'tipo', 'monto', 'moneda__codigo', 'emisor__id', 'receptor__id', 'estado'
            )

            ingresos = Decimal('0.00')
            egresos = Decimal('0.00')
            movimientos = []

            for transaccion in transacciones:
                monto = transaccion.monto if transaccion.estado == 'EXITOSA' else Decimal('0.00')
                es_ingreso = transaccion.receptor == usuario
                if es_ingreso:
                    ingresos += monto
                else:
                    egresos += monto
                movimientos.append({
                    "fecha": transaccion.fecha_creacion,
                    "tipo": transaccion.tipo,
                    "monto": monto,
                    "moneda": transaccion.moneda.codigo,
                    "es_ingreso": es_ingreso,
                    "estado": transaccion.estado
                })

            response = {
                "ingresos": ingresos,
                "egresos": egresos,
                "saldo_neto": ingresos - egresos,
                "movimientos": movimientos,
                "metadatos": {
                    "periodo": periodo,
                    "fecha_inicio": fecha_inicio,
                    "fecha_fin": fecha_fin,
                    "total_movimientos": len(movimientos)
                }
            }

            logger.debug(f"[Movimientos] Resumen para {usuario.username}: {ingresos} ingresos, {egresos} egresos")
            return response

        except ValidationError as ve:
            logger.error(f"Error de validación al generar movimientos para {usuario.username}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al generar movimientos para {usuario.username}: {str(e)}")
            raise ValidationError(_("Error al generar el resumen de movimientos."))

    @staticmethod
    def estadisticas_por_rol(rol, fecha_inicio=None, fecha_fin=None):
        """
        Calcula métricas financieras y de actividad para un rol específico.

        Args:
            rol (str): Rol a analizar (cliente, vendedor, distribuidor, admin).
            fecha_inicio (date, optional): Fecha inicial del filtro.
            fecha_fin (date, optional): Fecha final del filtro.

        Returns:
            dict: Estadísticas del rol (usuarios activos, saldo promedio, transacciones).

        Raises:
            ValidationError: Si el rol o las fechas son inválidos.
        """
        # Validar rol y fechas
        if rol not in [choice[0] for choice in User.ROLE_CHOICES]:
            logger.error(f"Rol inválido: {rol}")
            raise ValidationError(_("Rol inválido."))
        if fecha_inicio and fecha_fin:
            Validaciones.validar_rango_fechas(fecha_inicio, fecha_fin)
        else:
            fecha_fin = timezone.now().date()
            fecha_inicio = fecha_fin - timedelta(days=30)

        try:
            # Obtener usuarios activos
            usuarios = User.objects.filter(
                rol=rol, is_active=True, deleted_at__isnull=True
            ).only('id', 'username')
            total_usuarios = usuarios.count()

            if total_usuarios == 0:
                logger.debug(f"No hay usuarios activos con rol {rol}")
                return {
                    "total_usuarios": 0,
                    "saldo_promedio": Decimal('0.00'),
                    "total_transacciones": 0,
                    "transacciones_promedio": Decimal('0.00'),
                    "metadatos": {
                        "rol": rol,
                        "fecha_inicio": fecha_inicio,
                        "fecha_fin": fecha_fin
                    }
                }

            # Calcular saldos promedio
            saldos = [SaldoService.consultar_saldo(u) for u in usuarios]
            saldo_promedio = sum(saldos, Decimal('0.00')) / total_usuarios if saldos else Decimal('0.00')

            # Calcular transacciones
            transacciones = Transaccion.objects.filter(
                Q(emisor__rol=rol) | Q(receptor__rol=rol),
                fecha_creacion__range=(fecha_inicio, fecha_fin)
            )
            total_transacciones = transacciones.count()
            transacciones_promedio = total_transacciones / total_usuarios if total_usuarios else Decimal('0.00')

            response = {
                "total_usuarios": total_usuarios,
                "saldo_promedio": saldo_promedio,
                "total_transacciones": total_transacciones,
                "transacciones_promedio": transacciones_promedio,
                "metadatos": {
                    "rol": rol,
                    "fecha_inicio": fecha_inicio,
                    "fecha_fin": fecha_fin
                }
            }

            logger.debug(f"[Estadísticas] Generadas para rol {rol}: {total_usuarios} usuarios, {saldo_promedio} promedio")
            return response

        except ValidationError as ve:
            logger.error(f"Error de validación al generar estadísticas para rol {rol}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al generar estadísticas para rol {rol}: {str(e)}")
            raise ValidationError(_("Error al generar estadísticas."))

    @staticmethod
    def resumen_transacciones_por_usuario(usuario, fecha_inicio=None, fecha_fin=None):
        """
        Proporciona un resumen detallado de transacciones para un usuario en un período.

        Args:
            usuario (User): Usuario autenticado.
            fecha_inicio (date, optional): Fecha inicial del filtro.
            fecha_fin (date, optional): Fecha final del filtro.

        Returns:
            dict: Resumen con totales, promedios, frecuencias y distribución por tipo.

        Raises:
            ValidationError: Si el usuario o las fechas son inválidos.
        """
        # Validar usuario y fechas
        if not AuthService.is_authenticated(usuario) or not AuthService.is_active(usuario):
            logger.error(f"Usuario {usuario.username} no autenticado o inactivo")
            raise ValidationError(_("Usuario no autenticado o inactivo."))
        if fecha_inicio and fecha_fin:
            Validaciones.validar_rango_fechas(fecha_inicio, fecha_fin)
        else:
            fecha_fin = timezone.now().date()
            fecha_inicio = fecha_fin - timedelta(days=30)

        try:
            # Obtener transacciones
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario),
                fecha_creacion__range=(fecha_inicio, fecha_fin)
            ).select_related('moneda')

            total_transacciones = transacciones.count()
            if total_transacciones == 0:
                logger.debug(f"No hay transacciones para {usuario.username} entre {fecha_inicio} y {fecha_fin}")
                return {
                    "total_transacciones": 0,
                    "monto_total": Decimal('0.00'),
                    "monto_promedio": Decimal('0.00'),
                    "frecuencia_por_mes": 0,
                    "distribucion_por_tipo": {},
                    "metadatos": {
                        "fecha_inicio": fecha_inicio,
                        "fecha_fin": fecha_fin
                    }
                }

            # Calcular métricas
            monto_total = transacciones.aggregate(total=Sum('monto'))['total'] or Decimal('0.00')
            monto_promedio = monto_total / total_transacciones
            dias_periodo = (fecha_fin - fecha_inicio).days or 1
            frecuencia_por_mes = (total_transacciones / dias_periodo) * 30  # Normalizado a 30 días

            # Distribución por tipo
            distribucion = transacciones.values('tipo').annotate(
                total_monto=Sum('monto'), count=Count('id')
            )
            distribucion_por_tipo = {
                item['tipo']: {
                    "monto": item['total_monto'],
                    "cantidad": item['count']
                } for item in distribucion
            }

            response = {
                "total_transacciones": total_transacciones,
                "monto_total": monto_total,
                "monto_promedio": monto_promedio,
                "frecuencia_por_mes": round(frecuencia_por_mes, 2),
                "distribucion_por_tipo": distribucion_por_tipo,
                "metadatos": {
                    "fecha_inicio": fecha_inicio,
                    "fecha_fin": fecha_fin,
                    "timestamp": timezone.now()
                }
            }

            logger.debug(f"[Transacciones] Resumen para {usuario.username}: {total_transacciones} transacciones")
            return response

        except ValidationError as ve:
            logger.error(f"Error de validación al generar resumen de transacciones para {usuario.username}: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error inesperado al generar resumen de transacciones para {usuario.username}: {str(e)}")
            raise ValidationError(_("Error al generar el resumen de transacciones."))