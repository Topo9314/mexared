# apps/ofertas/forms.py

from django import forms
from decimal import Decimal
from django.core.exceptions import ValidationError

from .models import (
    Oferta,
    MargenDistribuidor,
    ListaPreciosEspecial,
    OfertaListaPreciosEspecial,
    ClienteListaAsignada,
    MargenVendedor
)
from django.utils.translation import gettext_lazy as _

# Centralized currency choices from models.py
from .models import CURRENCY_CHOICES

class OfferMarginForm(forms.ModelForm):
    """
    Form for admin to assign margins to distributors, supporting multi-currency and audit.
    Enhanced with strict validation and international readiness.
    """
    class Meta:
        model = MargenDistribuidor
        fields = [
            'oferta',
            'precio_distribuidor',
            'precio_vendedor',
            'precio_cliente',
            'moneda'
        ]
        widgets = {
            'oferta': forms.Select(attrs={'class': 'form-control international'}),
            'precio_distribuidor': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
            'precio_vendedor': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
            'precio_cliente': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
            'moneda': forms.Select(choices=CURRENCY_CHOICES, attrs={'class': 'form-control international'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        oferta = cleaned_data.get("oferta")
        costo_base = oferta.costo_base if oferta else Decimal('0.00')
        pd = Decimal(str(cleaned_data.get("precio_distribuidor") or Decimal('0.00')))
        pv = Decimal(str(cleaned_data.get("precio_vendedor") or Decimal('0.00')))
        pc = Decimal(str(cleaned_data.get("precio_cliente") or Decimal('0.00')))
        moneda = cleaned_data.get("moneda")

        if not oferta or pd is None or pv is None or pc is None or not moneda:
            return cleaned_data
        if pd < Decimal('0.00'):
            raise ValidationError(_("El precio distribuidor no puede ser negativo."))
        if pv < Decimal('0.00'):
            raise ValidationError(_("El precio vendedor no puede ser negativo."))
        if pc < Decimal('0.00'):
            raise ValidationError(_("El precio cliente no puede ser negativo."))
        if oferta.moneda != moneda:
            raise ValidationError(_("La moneda seleccionada debe coincidir con la moneda de la oferta (%(currency)s).") % {'currency': oferta.moneda})
        if pd < costo_base:
            raise ValidationError(_("El precio distribuidor no puede ser menor al costo base de %(cost)s.") % {'cost': costo_base})
        if pv < pd:
            raise ValidationError(_("El precio vendedor no puede ser menor al precio distribuidor."))
        if pc < pv:
            raise ValidationError(_("El precio cliente no puede ser menor al precio vendedor."))

class SpecialPriceListForm(forms.ModelForm):
    """
    Form for admin to create special price lists, supporting multi-lingual and multi-currency.
    Enhanced with validation for uniqueness and consistency.
    """
    class Meta:
        model = ListaPreciosEspecial
        fields = ['nombre', 'descripcion', 'moneda', 'language']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control international'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control international'}),
            'moneda': forms.Select(choices=CURRENCY_CHOICES, attrs={'class': 'form-control international'}),
            'language': forms.Select(choices=[('es', _('Spanish')), ('en', _('English')), ('pt', _('Portuguese'))], attrs={'class': 'form-control international'}),
        }

    def clean_nombre(self):
        nombre = self.cleaned_data.get('nombre')
        if ListaPreciosEspecial.objects.filter(nombre=nombre).exists():
            raise ValidationError(_("El nombre de la lista ya existe. Por favor, elige otro."))
        return nombre

class OfferSpecialPriceForm(forms.ModelForm):
    """
    Form for admin to assign special prices to offers within a VIP list.
    Enhanced with currency and base cost validation.
    """
    class Meta:
        model = OfertaListaPreciosEspecial
        fields = ['oferta', 'precio_cliente_especial']
        widgets = {
            'oferta': forms.Select(attrs={'class': 'form-control international'}),
            'precio_cliente_especial': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        oferta = cleaned_data.get("oferta")
        precio_especial = Decimal(str(cleaned_data.get("precio_cliente_especial") or Decimal('0.00')))

        if not oferta or precio_especial is None:
            return cleaned_data
        if precio_especial < Decimal('0.00'):
            raise ValidationError(_("El precio especial no puede ser negativo."))
        if oferta and precio_especial < oferta.costo_base:
            raise ValidationError(_("El precio especial no puede ser menor al costo base de %(cost)s.") % {'cost': oferta.costo_base})

class ClientPriceListAssignForm(forms.ModelForm):
    """
    Form for admin to assign a special price list to a client.
    Enhanced with validation for active lists.
    """
    class Meta:
        model = ClienteListaAsignada
        fields = ['lista']
        widgets = {
            'lista': forms.Select(attrs={'class': 'form-control international'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['lista'].queryset = ListaPreciosEspecial.objects.filter(activo=True)

class VendedorMarginForm(forms.ModelForm):
    """
    Form for distributor to assign margins to vendors, with role-based restrictions.
    Updated to use MargenDistribuidor relationship.
    """
    class Meta:
        model = MargenVendedor
        fields = ['margen_distribuidor', 'precio_vendedor', 'precio_cliente']
        widgets = {
            'margen_distribuidor': forms.Select(attrs={'class': 'form-control international'}),
            'precio_vendedor': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
            'precio_cliente': forms.NumberInput(attrs={'class': 'form-control international', 'step': '0.01', 'min': '0'}),
        }

    def __init__(self, *args, **kwargs):
        self.distribuidor = kwargs.pop('distribuidor', None)
        super().__init__(*args, **kwargs)
        if self.distribuidor:
            self.fields['margen_distribuidor'].queryset = MargenDistribuidor.objects.filter(
                distribuidor=self.distribuidor,
                activo=True
            ).select_related('oferta')

    def clean(self):
        cleaned_data = super().clean()
        margen_distribuidor = cleaned_data.get("margen_distribuidor")
        precio_vendedor = Decimal(str(cleaned_data.get("precio_vendedor") or Decimal('0.00')))
        precio_cliente = Decimal(str(cleaned_data.get("precio_cliente") or Decimal('0.00')))
        moneda = margen_distribuidor.moneda if margen_distribuidor else getattr(settings, 'CURRENCY_DEFAULT', 'MXN')

        if not margen_distribuidor or precio_vendedor is None or precio_cliente is None:
            return cleaned_data
        if precio_vendedor < Decimal('0.00'):
            raise ValidationError(_("El precio vendedor no puede ser negativo."))
        if precio_cliente < Decimal('0.00'):
            raise ValidationError(_("El precio cliente no puede ser negativo."))
        if precio_vendedor < margen_distribuidor.precio_distribuidor:
            raise ValidationError(_("El precio vendedor no puede ser menor al precio distribuidor de %(price)s.") % {'price': margen_distribuidor.precio_distribuidor})
        if precio_cliente < precio_vendedor:
            raise ValidationError(_("El precio cliente no puede ser menor al precio vendedor."))
        if precio_cliente > margen_distribuidor.precio_cliente:
            raise ValidationError(_("El precio cliente no puede superar el margen permitido de %(price)s.") % {'price': margen_distribuidor.precio_cliente})
        if moneda != margen_distribuidor.moneda:
            raise ValidationError(_("La moneda debe coincidir con la del margen distribuidor (%(currency)s).") % {'currency': margen_distribuidor.moneda})



            