"""
Servicio de transacciones para MexaRed.
Centraliza la creación, consulta, filtrado, resumen y reverso de objetos Transaccion,
con validaciones de permisos, auditoría detallada y optimización para alto volumen.
Diseñado para entornos internacionales, enfocado en México.

Incluye:
- Creación normal de transacciones (asignación, consumo, etc.)
- Reverso de transacciones con justificación
- Soporte internacional (multimoneda) con validación de código
- Registro detallado en UserChangeLog
"""

import logging
from decimal import Decimal
from django.db import transaction
from django.db.models import Q, Sum
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.users.models import User, UserChangeLog
from apps.users.services.auth_service import AuthService
from apps.transacciones.models import Transaccion, Moneda, MotivoTransaccion, AuditoriaTransaccion

# Configuración de logging para monitoreo en producción
logger = logging.getLogger(__name__)

# Constante para el tipo de transacción de reverso
TIPO_REVERSO = 'REVERSO'

class TransaccionService:
    """
    Servicio para gestionar objetos Transaccion en MexaRed.
    Proporciona creación, consulta, filtrado, resumen y reverso de transacciones,
    con validaciones de permisos y auditoría.
    """

    @staticmethod
    @transaction.atomic
    def crear_transaccion(
        tipo,
        monto,
        emisor=None,
        receptor=None,
        motivo_codigo=None,
        descripcion=None,
        realizado_por=None,
        moneda_codigo='MXN',
        referencia_externa=None
    ):
        """
        Crea y guarda una transacción con validaciones, sin modificar saldos.

        Args:
            tipo (str): Tipo de transacción (ASIGNACION, CONSUMO_API, etc.).
            monto (Decimal): Monto de la transacción.
            emisor (User, optional): Usuario emisor.
            receptor (User, optional): Usuario receptor.
            motivo_codigo (str, optional): Código del motivo de la transacción.
            descripcion (str, optional): Descripción de la transacción.
            realizado_por (User, optional): Usuario que realiza la transacción.
            moneda_codigo (str, optional): Código de la moneda (default: MXN).
            referencia_externa (str, optional): Referencia externa.

        Returns:
            Transaccion: Instancia de la transacción creada.

        Raises:
            ValidationError: Si no se cumplen las validaciones.
        """
        # Validar permisos del usuario que realiza la transacción
        if realizado_por and not AuthService.has_permission(realizado_por, 'can_assign_saldo'):
            logger.error(f"Usuario {realizado_por.username} no tiene permisos para crear transacciones")
            raise ValidationError(_("Solo administradores o distribuidores pueden crear transacciones."))

        # Validar tipo de transacción
        if tipo not in dict(Transaccion.TIPO_CHOICES).keys():
            logger.error(f"Tipo de transacción inválido: {tipo}")
            raise ValidationError(_("Tipo de transacción inválido."))

        # Validar monto
        if not isinstance(monto, Decimal) or monto <= 0:
            logger.error(f"Monto inválido: {monto}")
            raise ValidationError(_("El monto debe ser mayor a cero."))

        # Validar roles
        if emisor and not (emisor.has_role('admin') or emisor.has_role('distribuidor')):
            logger.error(f"Emisor {emisor.username} no es administrador ni distribuidor")
            raise ValidationError(_("El emisor debe ser un administrador o distribuidor."))
        if receptor and not (receptor.has_role('distribuidor') or receptor.has_role('vendedor')):
            logger.error(f"Receptor {receptor.username} no es distribuidor ni vendedor")
            raise ValidationError(_("El receptor debe ser un distribuidor o vendedor."))
        if emisor and receptor and emisor == receptor:
            logger.error(f"Emisor y receptor no pueden ser el mismo: {emisor.username}")
            raise ValidationError(_("El emisor y el receptor no pueden ser el mismo usuario."))

        # Obtener moneda
        try:
            moneda = Moneda.objects.get(codigo=moneda_codigo)
        except Moneda.DoesNotExist:
            logger.error(f"Moneda {moneda_codigo} no encontrada")
            raise ValidationError(_("Moneda no configurada."))

        # Obtener motivo
        motivo = None
        if motivo_codigo:
            try:
                motivo = MotivoTransaccion.objects.get(codigo=motivo_codigo, activo=True)
            except MotivoTransaccion.DoesNotExist:
                logger.warning(f"Motivo {motivo_codigo} no encontrado o inactivo")

        # Crear transacción
        transaccion = Transaccion.objects.create(
            tipo=tipo,
            monto=monto,
            moneda=moneda,
            emisor=emisor,
            receptor=receptor,
            motivo=motivo,
            descripcion=descripcion or f"Transacción {tipo}",
            realizado_por=realizado_por,
            estado='EXITOSA',
            referencia_externa=referencia_externa
        )

        # Registrar en UserChangeLog
        user = receptor or emisor
        if user:
            UserChangeLog.objects.create(
                user=user,
                changed_by=realizado_por,
                change_type='update',
                change_description=f"Creación de transacción {tipo}",
                details={
                    "transaccion_id": transaccion.id,
                    "monto": str(monto),
                    "moneda": moneda.codigo,
                    "tipo": tipo
                }
            )

        logger.info(f"Transacción creada: {transaccion.id} ({tipo}) por {realizado_por.username if realizado_por else 'Sistema'}")
        return transaccion

    @staticmethod
    @transaction.atomic
    def crear_reverso_de_transaccion(transaccion_original, realizado_por, justificacion, motivo_codigo=None, referencia_externa=None):
        """
        Crea una transacción de reverso para una transacción existente, solicitada por un distribuidor.

        Args:
            transaccion_original (Transaccion): La transacción original a revertir.
            realizado_por (User): Usuario que solicita el reverso (debe ser distribuidor o admin).
            justificacion (str): Justificación obligatoria para el reverso (mínimo 5 caracteres).
            motivo_codigo (str, optional): Código del motivo para el reverso.
            referencia_externa (str, optional): Referencia externa para el reverso.

        Returns:
            Transaccion: Instancia de la transacción de reverso creada.

        Raises:
            ValidationError: Si no se cumplen las validaciones (permisos, estado, saldo, etc.).
        """
        # Validar permisos
        if not (realizado_por.has_role('distribuidor') or realizado_por.has_role('admin')):
            logger.error(f"Usuario {realizado_por.username} no tiene permisos para reversar transacciones")
            raise ValidationError(_("Solo distribuidores o administradores pueden reversar transacciones."))

        # Validar que el usuario sea el emisor original o admin
        if not (realizado_por.has_role('admin') or transaccion_original.emisor == realizado_por):
            logger.error(f"Usuario {realizado_por.username} no es el emisor original ni admin")
            raise ValidationError(_("Solo el emisor original o un administrador pueden reversar esta transacción."))

        # Validar estado de la transacción original
        if transaccion_original.estado != 'EXITOSA':
            logger.error(f"Transacción {transaccion_original.id} no está en estado EXITOSA")
            raise ValidationError(_("Solo se pueden reversar transacciones exitosas."))

        # Validar que no se haya revertido previamente
        if Transaccion.objects.filter(
            tipo=TIPO_REVERSO,
            referencia_externa=f"REVERSO_{transaccion_original.id}"
        ).exists():
            logger.error(f"Transacción {transaccion_original.id} ya fue revertida")
            raise ValidationError(_("Esta transacción ya ha sido revertida."))

        # Validar justificación
        if not justificacion or len(justificacion.strip()) < 5:
            logger.error(f"Justificación inválida: {justificacion}")
            raise ValidationError(_("La justificación es obligatoria y debe tener al menos 5 caracteres."))

        # Validar saldo disponible del vendedor (receptor original)
        if transaccion_original.receptor:
            try:
                relacion = transaccion_original.receptor.perfil_distribuidor
                if relacion.saldo_disponible < transaccion_original.monto:
                    logger.error(f"Vendedor {transaccion_original.receptor.username} tiene saldo insuficiente")
                    raise ValidationError(_("El vendedor no tiene suficiente saldo para el reverso."))
                if relacion.moneda != transaccion_original.moneda.codigo:
                    logger.error(f"Moneda del vendedor {relacion.moneda} no coincide con {transaccion_original.moneda.codigo}")
                    raise ValidationError(_("La moneda del vendedor no coincide con la de la transacción."))
            except AttributeError:
                logger.error(f"Vendedor {transaccion_original.receptor.username} no tiene perfil asociado")
                raise ValidationError(_("El vendedor no tiene un perfil asociado."))

        # Validar moneda
        # TODO: En el futuro, implementar conversión de divisas si la moneda del receptor es diferente
        moneda = transaccion_original.moneda

        # Obtener motivo
        motivo = None
        if motivo_codigo:
            try:
                motivo = MotivoTransaccion.objects.get(codigo=motivo_codigo, activo=True)
            except MotivoTransaccion.DoesNotExist:
                logger.warning(f"Motivo {motivo_codigo} no encontrado o inactivo")

        # Crear transacción de reverso
        transaccion_reverso = Transaccion.objects.create(
            tipo=TIPO_REVERSO,
            monto=transaccion_original.monto,
            moneda=moneda,
            emisor=transaccion_original.receptor,  # El vendedor ahora es el emisor
            receptor=transaccion_original.emisor,  # El distribuidor ahora es el receptor
            motivo=motivo,
            descripcion=f"Reverso de transacción {transaccion_original.id}: {justificacion}",
            realizado_por=realizado_por,
            estado='EXITOSA',
            referencia_externa=f"REVERSO_{transaccion_original.id}"
        )

        # Actualizar saldos
        if transaccion_original.receptor and transaccion_original.emisor:
            try:
                # Descontar saldo del vendedor
                relacion_vendedor = transaccion_original.receptor.perfil_distribuidor
                relacion_vendedor.descontar_saldo(
                    monto=transaccion_original.monto,
                    moneda=moneda.codigo,
                    changed_by=realizado_por
                )

                # Aumentar saldo del distribuidor
                perfil_distribuidor = transaccion_original.emisor.perfil_distribuidor_rel
                perfil_distribuidor.saldo_actual += transaccion_original.monto
                perfil_distribuidor.save(update_fields=['saldo_actual'])
            except AttributeError:
                logger.error("Error al actualizar saldos: perfiles no encontrados")
                raise ValidationError(_("Error al actualizar saldos: perfiles no encontrados."))

        # Registrar en UserChangeLog
        UserChangeLog.objects.create(
            user=transaccion_original.receptor,
            changed_by=realizado_por,
            change_type='update',
            change_description=f"Reverso de transacción {transaccion_original.id}",
            details={
                "transaccion_original_id": transaccion_original.id,
                "transaccion_reverso_id": transaccion_reverso.id,
                "monto": str(transaccion_original.monto),
                "moneda": moneda.codigo,
                "justificacion": justificacion
            }
        )

        # Registrar auditoría
        AuditoriaTransaccion.objects.create(
            transaccion=transaccion_reverso,
            tipo='CREACION',
            usuario=realizado_por,
            detalles={
                "evento": "Creación de transacción de reverso",
                "transaccion_original_id": transaccion_original.id,
                "justificacion": justificacion
            }
        )

        logger.info(f"Transacción de reverso creada: {transaccion_reverso.id} para transacción {transaccion_original.id} por {realizado_por.username}")
        return transaccion_reverso

    @staticmethod
    def listar_transacciones_por_usuario(usuario, page_size=25, page=1):
        """
        Lista todas las transacciones donde el usuario es emisor o receptor.

        Args:
            usuario (User): Instancia del modelo User.
            page_size (int): Tamaño de la página para paginación (default: 25).
            page (int): Número de página (default: 1).

        Returns:
            QuerySet: Transacciones filtradas, paginadas.
        """
        try:
            offset = (page - 1) * page_size
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario)
            ).select_related('moneda', 'motivo', 'emisor', 'receptor', 'realizado_por')\
             .order_by('-fecha_creacion')[offset:offset + page_size]

            logger.debug(f"Listado de transacciones para {usuario.username}: {transacciones.count()} encontradas")
            return transacciones
        except Exception as e:
            logger.error(f"Error al listar transacciones para {usuario.username}: {str(e)}")
            return Transaccion.objects.none()

    @staticmethod
    def buscar_transaccion_por_id(transaccion_id, usuario=None):
        """
        Busca una transacción por su ID, restringiendo acceso según usuario.

        Args:
            transaccion_id (int): ID de la transacción.
            usuario (User, optional): Usuario que realiza la consulta (para permisos).

        Returns:
            Transaccion: Instancia de la transacción encontrada.

        Raises:
            Transaccion.DoesNotExist: Si no se encuentra la transacción.
            ValidationError: Si el usuario no tiene acceso.
        """
        try:
            transaccion = Transaccion.objects.select_related('moneda', 'motivo', 'emisor', 'receptor', 'realizado_por')\
                            .get(id=transaccion_id)

            if usuario:
                if not (AuthService.is_admin(usuario) or transaccion.emisor == usuario or transaccion.receptor == usuario):
                    logger.error(f"Usuario {usuario.username} no tiene acceso a transacción {transaccion_id}")
                    raise ValidationError(_("No tienes acceso a esta transacción."))

            logger.debug(f"Transacción encontrada: {transaccion_id}")
            return transaccion
        except Transaccion.DoesNotExist:
            logger.error(f"Transacción no encontrada: {transaccion_id}")
            raise
        except Exception as e:
            logger.error(f"Error al buscar transacción {transaccion_id}: {str(e)}")
            raise ValidationError(_("Error al buscar la transacción."))

    @staticmethod
    def filtrar_transacciones_por_fecha(usuario, fecha_inicio, fecha_fin, page_size=25, page=1):
        """
        Filtra transacciones por rango de fechas para un usuario.

        Args:
            usuario (User): Instancia del modelo User.
            fecha_inicio (date): Fecha inicial del filtro.
            fecha_fin (date): Fecha final del filtro.
            page_size (int): Tamaño de la página para paginación (default: 25).
            page (int): Número de página (default: 1).

        Returns:
            QuerySet: Transacciones filtradas, paginadas.

        Raises:
            ValidationError: Si las fechas son inválidas.
        """
        if fecha_inicio > fecha_fin:
            logger.error(f"Rango de fechas inválido: {fecha_inicio} > {fecha_fin}")
            raise ValidationError(_("La fecha de inicio no puede ser posterior a la fecha final."))

        try:
            offset = (page - 1) * page_size
            transacciones = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario),
                fecha_creacion__range=(fecha_inicio, fecha_fin)
            ).select_related('moneda', 'motivo', 'emisor', 'receptor', 'realizado_por')\
             .order_by('-fecha_creacion')[offset:offset + page_size]

            logger.debug(f"Filtrado de transacciones para {usuario.username}: {transacciones.count()} encontradas")
            return transacciones
        except Exception as e:
            logger.error(f"Error al filtrar transacciones para {usuario.username}: {str(e)}")
            return Transaccion.objects.none()

    @staticmethod
    def resumir_totales_por_tipo(usuario):
        """
        Resume los totales de transacciones agrupados por tipo para un usuario.

        Args:
            usuario (User): Instancia del modelo User.

        Returns:
            dict: Totales por tipo de transacción (ej. {'ASIGNACION': 1000.00, 'CONSUMO_API': 500.00}).

        Raises:
            ValidationError: Si ocurre un error en la consulta.
        """
        try:
            totales = Transaccion.objects.filter(
                Q(emisor=usuario) | Q(receptor=usuario)
            ).values('tipo').annotate(total_monto=Sum('monto')).order_by('tipo')

            resumen = {item['tipo']: item['total_monto'] for item in totales}
            logger.debug(f"Resumen de totales por tipo para {usuario.username}: {resumen}")
            return resumen
        except Exception as e:
            logger.error(f"Error al resumir totales para {usuario.username}: {str(e)}")
            raise ValidationError(_("Error al generar el resumen de transacciones."))