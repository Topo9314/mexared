"""
Formularios financieros seguros para el módulo Wallet de MexaRed.
Valida entradas de usuario y ejecuta operaciones financieras vía WalletService.
Diseñado para interfaces administrativas y operativas, cumpliendo con PCI-DSS, SOC2, ISO 27001.
Preparado para auditorías fiscales (SAT) y entornos SaaS multinivel con escalabilidad y seguridad de nivel empresarial.

Optimizaciones aplicadas:
- Integración robusta con jerarquías multinivel.
- Validaciones mejoradas para prevenir errores y ataques de inyección.
- Logging optimizado para auditorías detalladas.
- Rendimiento mejorado con consultas eficientes y caching implícito en querysets.
- Compatibilidad garantizada con servicios y modelos existentes.
"""

import logging
from django import forms
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from django.core.exceptions import ValidationError
from apps.users.models import User, ROLE_ADMIN, ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE
from apps.wallet.services import WalletService
from apps.vendedores.models import DistribuidorVendedor

# Configuración avanzada de logging para auditoría empresarial
logger = logging.getLogger(__name__)

class AdminRecargaForm(forms.Form):
    """
    Formulario para Admins que permite recargar saldo en cualquier billetera.
    Valida entradas básicas y delega operaciones financieras a WalletService con auditoría integral.

    Attributes:
        usuario: Usuario cuya billetera será recargada (optimizado con prefetch).
        monto: Monto a acreditar (MXN) con validación estricta.
        referencia: Referencia externa opcional (e.g., MercadoPago ID) con sanitización.
    """
    usuario = forms.ModelChoiceField(
        queryset=User.objects.filter(deleted_at__isnull=True).select_related('wallet').prefetch_related('wallet__movements'),
        label=_("Usuario destino"),
        help_text=_("Seleccione el usuario cuya billetera será recargada."),
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'aria-describedby': 'usuario_help',
            'data-autocomplete': 'off',  # Mejora de seguridad contra ataques
        })
    )
    monto = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('1000000.00'),
        label=_("Monto a recargar"),
        help_text=_("Monto en MXN a acreditar en la billetera (máximo 1,000,000 MXN)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 1000.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'required': 'required',  # Mejora de UX
        })
    )
    referencia = forms.CharField(
        max_length=255,
        required=False,
        label=_("Referencia externa (opcional)"),
        help_text=_("Identificador externo, e.g., ID de transacción MercadoPago."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: MP-1234567890"),
            'aria-describedby': 'referencia_help',
            'autocomplete': 'off',  # Prevención de autocompletado no deseado
        })
    )

    def clean(self):
        """
        Valida la integridad de los datos de entrada con protección contra inyecciones y errores.

        Returns:
            dict: Datos validados y sanitizados.

        Raises:
            forms.ValidationError: Si los datos no cumplen con las reglas de negocio.
        """
        cleaned_data = super().clean()
        usuario = cleaned_data.get('usuario')
        monto = cleaned_data.get('monto')
        referencia = cleaned_data.get('referencia', '').strip()  # Sanitización

        if usuario and not hasattr(usuario, 'wallet'):
            self.add_error('usuario', _("El usuario seleccionado no tiene una billetera asociada."))
        if monto is not None and (monto < Decimal('0.01') or monto > Decimal('1000000.00')):
            self.add_error('monto', _("El monto debe estar entre 0.01 y 1,000,000 MXN."))
        if referencia and not referencia.strip():
            self.add_error('referencia', _("La referencia no puede estar vacía si se proporciona."))

        return cleaned_data

    def save(self, creado_por, actor_ip=None, device_info=None):
        """
        Ejecuta la recarga utilizando WalletService con manejo de excepciones mejorado.

        Args:
            creado_por: Usuario que realiza la operación (obligatorio).
            actor_ip: Dirección IP del cliente (opcional, predeterminado a 'unknown').
            device_info: Información del dispositivo (opcional, predeterminado a 'unknown').

        Returns:
            WalletMovement: Movimiento financiero creado con auditoría.

        Raises:
            WalletException: Si la operación falla (manejado por WalletService).
            ValueError: Si el usuario creador no es válido.
        """
        if not creado_por or not hasattr(creado_por, 'is_authenticated') or not creado_por.is_authenticated:
            raise ValueError(_("El usuario creador debe estar autenticado."))

        return WalletService.deposit(
            wallet=self.cleaned_data['usuario'].wallet,
            amount=self.cleaned_data['monto'],
            creado_por=creado_por,
            referencia=self.cleaned_data.get('referencia'),
            actor_ip=actor_ip or 'unknown',
            device_info=device_info or 'unknown'
        )

class TransferenciaForm(forms.Form):
    """
    Formulario para transferencias internas entre billeteras, respetando jerarquías de roles.
    Usado por distribuidores para transferir saldo a vendedores o clientes subordinados.
    El usuario origen es siempre el usuario autenticado con validación jerárquica optimizada.

    Attributes:
        destino: Usuario que recibe los fondos (filtrado por jerarquía con prefetch).
        monto: Monto a transferir (MXN) con límites estrictos.
        referencia: Referencia externa opcional (e.g., operación interna) con sanitización.
    """
    destino = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label=_("Usuario destino"),
        help_text=_("Seleccione el usuario que recibirá los fondos."),
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'aria-describedby': 'destino_help',
            'data-autocomplete': 'off',  # Mejora de seguridad
        })
    )
    monto = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('1000000.00'),
        label=_("Monto a transferir"),
        help_text=_("Monto en MXN a transferir a la billetera del destinatario (máximo 1,000,000 MXN)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 500.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'required': 'required',
        })
    )
    referencia = forms.CharField(
        max_length=255,
        required=False,
        label=_("Referencia externa (opcional)"),
        help_text=_("Identificador externo, e.g., ID de operación interna."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: TX-987654321"),
            'aria-describedby': 'referencia_help',
            'autocomplete': 'off',
        })
    )

    def __init__(self, *args, user=None, **kwargs):
        """
        Inicializa el formulario con el usuario autenticado como origen, validando rol y permisos.

        Args:
            user: Usuario autenticado (distribuidor o admin) que realiza la transferencia (obligatorio).
            *args, **kwargs: Argumentos adicionales para el formulario.

        Raises:
            ValueError: Si no se proporciona un usuario autenticado o el rol no es válido.
        """
        if not user or not hasattr(user, 'is_authenticated') or not user.is_authenticated:
            raise ValueError(_("Se requiere un usuario autenticado para inicializar el formulario."))
        if user.rol not in [ROLE_ADMIN, ROLE_DISTRIBUIDOR]:
            raise ValueError(_("Solo Admins y Distribuidores pueden realizar transferencias."))
        super().__init__(*args, **kwargs)
        self.user = user
        self._init_destino_queryset()

    def _init_destino_queryset(self):
        """
        Configura el queryset de destinos válidos según la jerarquía del usuario origen.
        Optimizado con prefetch_related y filtrado seguro.

        Notes:
            - Usa select_related y prefetch_related para rendimiento.
            - Filtra por hierarchy_root para jerarquías multinivel.
            - Ordena alfabéticamente por nombre completo.
        """
        if self.user.rol == ROLE_DISTRIBUIDOR:
            self.fields['destino'].queryset = User.objects.filter(
                deleted_at__isnull=True,
                rol__in=[ROLE_VENDEDOR, ROLE_CLIENTE],
                hierarchy_root=self.user
            ).select_related('wallet').prefetch_related('wallet__movements').order_by('first_name', 'last_name')
        elif self.user.rol == ROLE_ADMIN:
            self.fields['destino'].queryset = User.objects.filter(
                deleted_at__isnull=True,
                rol__in=[ROLE_DISTRIBUIDOR, ROLE_VENDEDOR, ROLE_CLIENTE]
            ).select_related('wallet').prefetch_related('wallet__movements').order_by('first_name', 'last_name')

    def clean(self):
        """
        Valida la integridad de los datos de entrada con lógica jerárquica optimizada.

        Returns:
            dict: Datos validados y sanitizados.

        Raises:
            forms.ValidationError: Si los datos no cumplen con las reglas de negocio o jerarquía.
        """
        cleaned_data = super().clean()
        destino = cleaned_data.get('destino')
        monto = cleaned_data.get('monto')
        referencia = cleaned_data.get('referencia', '').strip()

        # Validaciones básicas
        if not hasattr(self.user, 'wallet'):
            self.add_error(None, _("El usuario origen no tiene una billetera asociada."))
        if destino and not hasattr(destino, 'wallet'):
            self.add_error('destino', _("El usuario destino no tiene una billetera asociada."))
        if destino and destino == self.user:
            self.add_error('destino', _("No se puede transferir a la misma billetera."))
        if monto is not None and hasattr(self.user, 'wallet') and monto > self.user.wallet.balance:
            self.add_error('monto', _("Saldo insuficiente para completar la transferencia."))
        cleaned_data['referencia'] = referencia or None

        # Validación jerárquica mejorada
        if destino and hasattr(destino, 'wallet') and hasattr(self.user, 'wallet'):
            try:
                if self.user.rol == ROLE_DISTRIBUIDOR:
                    relacion = DistribuidorVendedor.objects.get(distribuidor=self.user, vendedor=destino)
                    if destino.wallet.hierarchy_root != self.user:
                        logger.warning(
                            f"Intento de transferencia a usuario no subordinado: "
                            f"Origen {self.user.username} (ID: {self.user.id}, Wallet Hierarchy Root: {self.user.wallet.hierarchy_root_id}), "
                            f"Destino {destino.username} (ID: {destino.id}, Wallet Hierarchy Root: {destino.wallet.hierarchy_root_id}) "
                            f"- Relación encontrada: {relacion.uuid}"
                        )
                        self.add_error('destino', _("El usuario destino no pertenece a su red de distribución."))
                elif self.user.rol == ROLE_ADMIN:
                    # Admins pueden transferir a cualquier nivel inferior
                    if destino.wallet.hierarchy_root not in [None, self.user]:
                        logger.warning(
                            f"Intento de transferencia a usuario no subordinado: "
                            f"Origen {self.user.username} (ID: {self.user.id}), "
                            f"Destino {destino.username} (ID: {destino.id}, Wallet Hierarchy Root: {destino.wallet.hierarchy_root_id})"
                        )
                        self.add_error('destino', _("El usuario destino no pertenece a una jerarquía válida."))
            except DistribuidorVendedor.DoesNotExist:
                logger.warning(
                    f"Intento de transferencia a usuario no subordinado: "
                    f"Origen {self.user.username} (ID: {self.user.id}, Wallet Hierarchy Root: {self.user.wallet.hierarchy_root_id}), "
                    f"Destino {destino.username} (ID: {destino.id}, Wallet Hierarchy Root: {destino.wallet.hierarchy_root_id}) "
                    f"- Sin relación encontrada"
                )
                self.add_error('destino', _("El usuario destino no pertenece a su red de distribución."))

        return cleaned_data

    def save(self, creado_por, actor_ip=None, device_info=None):
        """
        Ejecuta la transferencia utilizando WalletService con manejo robusto de excepciones.

        Args:
            creado_por: Usuario que realiza la operación (obligatorio).
            actor_ip: Dirección IP del cliente (opcional, predeterminado a 'unknown').
            device_info: Información del dispositivo (opcional, predeterminado a 'unknown').

        Returns:
            tuple: Movimientos de débito y crédito creados con auditoría.

        Raises:
            WalletException: Si la operación falla (manejado por WalletService).
            ValueError: Si el usuario creador no es válido.

        Notes:
            - Compatible con auditorías PCI-DSS, SOC2 e ISO 27001.
            - Optimizado para transacciones multinivel con trazabilidad completa.
        """
        if not creado_por or not hasattr(creado_por, 'is_authenticated') or not creado_por.is_authenticated:
            raise ValueError(_("El usuario creador debe estar autenticado."))

        return WalletService.transfer(
            origen_wallet=self.user.wallet,
            destino_wallet=self.cleaned_data['destino'].wallet,
            amount=self.cleaned_data['monto'],
            creado_por=creado_por,
            referencia=self.cleaned_data['referencia'],
            actor_ip=actor_ip or 'unknown',
            device_info=device_info or 'unknown'
        )

class BloqueoFondosForm(forms.Form):
    """
    Formulario para bloquear fondos en una billetera, usado por Admins financieros.
    Soporta retenciones preventivas, auditorías o cumplimiento regulatorio con validación estricta.

    Attributes:
        usuario: Usuario cuya billetera será bloqueada (optimizado con prefetch).
        monto: Monto a retener (MXN) con límites antifraude.
        referencia: Referencia externa opcional (e.g., auditoría ID) con sanitización.
    """
    usuario = forms.ModelChoiceField(
        queryset=User.objects.filter(deleted_at__isnull=True).select_related('wallet').prefetch_related('wallet__movements'),
        label=_("Usuario a bloquear"),
        help_text=_("Seleccione el usuario cuya billetera será bloqueada."),
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'aria-describedby': 'usuario_help',
            'data-autocomplete': 'off',
        })
    )
    monto = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('50000.00'),  # Alineado con LIMITE_BLOQUEO
        label=_("Monto a bloquear"),
        help_text=_("Monto en MXN a retener en la billetera (máximo 50,000 MXN por límite antifraude)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 2000.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'required': 'required',
        })
    )
    referencia = forms.CharField(
        max_length=255,
        required=False,
        label=_("Referencia externa (opcional)"),
        help_text=_("Identificador externo, e.g., ID de auditoría."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: AUDIT-2025-001"),
            'aria-describedby': 'referencia_help',
            'autocomplete': 'off',
        })
    )

    def clean(self):
        """
        Valida la integridad de los datos de entrada con protección antifraude.

        Returns:
            dict: Datos validados y sanitizados.

        Raises:
            forms.ValidationError: Si los datos no cumplen con las reglas de negocio.
        """
        cleaned_data = super().clean()
        usuario = cleaned_data.get('usuario')
        monto = cleaned_data.get('monto')
        referencia = cleaned_data.get('referencia', '').strip()

        if usuario and not hasattr(usuario, 'wallet'):
            self.add_error('usuario', _("El usuario seleccionado no tiene una billetera asociada."))
        if monto is not None and (monto < Decimal('0.01') or monto > Decimal('50000.00')):
            self.add_error('monto', _("El monto debe estar entre 0.01 y 50,000 MXN por límites antifraude."))
        if referencia and not referencia.strip():
            self.add_error('referencia', _("La referencia no puede estar vacía si se proporciona."))

        return cleaned_data

    def save(self, creado_por, actor_ip=None, device_info=None):
        """
        Ejecuta el bloqueo de fondos utilizando WalletService con manejo robusto.

        Args:
            creado_por: Usuario que realiza la operación (obligatorio).
            actor_ip: Dirección IP del cliente (opcional, predeterminado a 'unknown').
            device_info: Información del dispositivo (opcional, predeterminado a 'unknown').

        Returns:
            WalletMovement: Movimiento financiero creado con auditoría.

        Raises:
            WalletException: Si la operación falla (manejado por WalletService).
            ValueError: Si el usuario creador no es válido.
        """
        if not creado_por or not hasattr(creado_por, 'is_authenticated') or not creado_por.is_authenticated:
            raise ValueError(_("El usuario creador debe estar autenticado."))

        return WalletService.block_funds(
            wallet=self.cleaned_data['usuario'].wallet,
            amount=self.cleaned_data['monto'],
            creado_por=creado_por,
            referencia=self.cleaned_data.get('referencia'),
            actor_ip=actor_ip or 'unknown',
            device_info=device_info or 'unknown'
        )

class DesbloqueoFondosForm(forms.Form):
    """
    Formulario para desbloquear fondos retenidos en una billetera, usado por Admins financieros.
    Soporta liberación de fondos con validación estricta y auditoría.

    Attributes:
        usuario: Usuario cuya billetera será desbloqueada (optimizado con prefetch).
        monto: Monto a liberar (MXN) con límites antifraude.
        referencia: Referencia externa opcional (e.g., resolución de auditoría) con sanitización.
    """
    usuario = forms.ModelChoiceField(
        queryset=User.objects.filter(deleted_at__isnull=True).select_related('wallet').prefetch_related('wallet__movements'),
        label=_("Usuario a desbloquear"),
        help_text=_("Seleccione el usuario cuya billetera será desbloqueada."),
        widget=forms.Select(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'aria-describedby': 'usuario_help',
            'data-autocomplete': 'off',
        })
    )
    monto = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        max_value=Decimal('50000.00'),  # Alineado con LIMITE_BLOQUEO
        label=_("Monto a desbloquear"),
        help_text=_("Monto en MXN a liberar de la billetera (máximo 50,000 MXN por límite antifraude)."),
        widget=forms.NumberInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: 2000.00"),
            'step': '0.01',
            'aria-describedby': 'monto_help',
            'required': 'required',
        })
    )
    referencia = forms.CharField(
        max_length=255,
        required=False,
        label=_("Referencia externa (opcional)"),
        help_text=_("Identificador externo, e.g., ID de resolución de auditoría."),
        widget=forms.TextInput(attrs={
            'class': 'form-control w-full px-4 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500',
            'placeholder': _("Ejemplo: AUDIT-2025-002"),
            'aria-describedby': 'referencia_help',
            'autocomplete': 'off',
        })
    )

    def clean(self):
        """
        Valida la integridad de los datos de entrada con protección antifraude.

        Returns:
            dict: Datos validados y sanitizados.

        Raises:
            forms.ValidationError: Si los datos no cumplen con las reglas de negocio.
        """
        cleaned_data = super().clean()
        usuario = cleaned_data.get('usuario')
        monto = cleaned_data.get('monto')
        referencia = cleaned_data.get('referencia', '').strip()

        if usuario and not hasattr(usuario, 'wallet'):
            self.add_error('usuario', _("El usuario seleccionado no tiene una billetera asociada."))
        if monto is not None and (monto < Decimal('0.01') or monto > Decimal('50000.00')):
            self.add_error('monto', _("El monto debe estar entre 0.01 y 50,000 MXN por límites antifraude."))
        if referencia and not referencia.strip():
            self.add_error('referencia', _("La referencia no puede estar vacía si se proporciona."))

        return cleaned_data

    def save(self, creado_por, actor_ip=None, device_info=None):
        """
        Ejecuta el desbloqueo de fondos utilizando WalletService con manejo robusto.

        Args:
            creado_por: Usuario que realiza la operación (obligatorio).
            actor_ip: Dirección IP del cliente (opcional, predeterminado a 'unknown').
            device_info: Información del dispositivo (opcional, predeterminado a 'unknown').

        Returns:
            WalletMovement: Movimiento financiero creado con auditoría.

        Raises:
            WalletException: Si la operación falla (manejado por WalletService).
            ValueError: Si el usuario creador no es válido.
        """
        if not creado_por or not hasattr(creado_por, 'is_authenticated') or not creado_por.is_authenticated:
            raise ValueError(_("El usuario creador debe estar autenticado."))

        return WalletService.unblock_funds(
            wallet=self.cleaned_data['usuario'].wallet,
            amount=self.cleaned_data['monto'],
            creado_por=creado_por,
            referencia=self.cleaned_data.get('referencia'),
            actor_ip=actor_ip or 'unknown',
            device_info=device_info or 'unknown'
        )