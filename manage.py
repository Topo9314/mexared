#!/usr/bin/env python
"""
🚀 MexaRed - Administrador de Comandos de Django

Este script ejecuta tareas administrativas usando Django.
Detecta automáticamente el entorno de ejecución (dev/prod)
según lo definido en el archivo .env (usando python-decouple).
"""

import os
import sys
from pathlib import Path
from decouple import config, UndefinedValueError

def main():
    """Punto de entrada para comandos administrativos de Django."""
    try:
        # Establece el entorno de configuración (dev o prod)
        settings_module = config('DJANGO_SETTINGS_MODULE', default='config.settings.dev')
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', settings_module)

    except UndefinedValueError as e:
        raise RuntimeError(
            "⚠️  No se ha definido DJANGO_SETTINGS_MODULE en el archivo .env.\n"
            "Asegúrate de tener un .env válido en la raíz del proyecto con esta variable definida.\n"
            "Ejemplo: DJANGO_SETTINGS_MODULE=config.settings.dev"
        ) from e

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "❌ No se pudo importar Django. ¿Está activado tu entorno virtual?\n"
            "Verifica que Django esté instalado correctamente."
        ) from exc

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
