#!/usr/bin/env python
"""
🚀 MexaRed – Django Command-Line Utility (versión enterprise)

— RESPONSABILIDADES PRINCIPALES —
1. Cargar de forma fiable el archivo .env situado en la raíz del proyecto
   (independiente del entorno o shell).
2. Resolver y validar el módulo de ajustes (`DJANGO_SETTINGS_MODULE`),
   con retro-compatibilidad a `config.settings.dev`.
3. Proveer mensajes de error claros y códigos de salida coherentes.
4. Ejecutar los comandos de gestión de Django con la máxima estabilidad.

© 2025 Wizard Cleaning Service LLC / MexaRed
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Final

# -----------------------------------------------------------------------------
# 0.  Dependencias externas
# -----------------------------------------------------------------------------
try:
    from decouple import Config, RepositoryEnv, UndefinedValueError
except ImportError as exc:  # decouple es fundamental
    print(
        "❌ Falta el paquete python-decouple.\n"
        "Instálalo dentro del entorno virtual:\n"
        "    $ pip install python-decouple",
        file=sys.stderr,
    )
    raise SystemExit(2) from exc

# -----------------------------------------------------------------------------
# 1.  Constantes y utilidades
# -----------------------------------------------------------------------------
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
ENV_FILE: Final[Path] = BASE_DIR / ".env"
DEFAULT_SETTINGS: Final[str] = "config.settings.dev"

# Cargamos el .env de forma explícita *antes* de cualquier lectura a config().
config = Config(RepositoryEnv(str(ENV_FILE)))


# -----------------------------------------------------------------------------
# 2.  Resolución y validación del módulo de ajustes
# -----------------------------------------------------------------------------
def _resolve_settings_module() -> str:
    """
    Devuelve la ruta con puntos al módulo de ajustes Django a utilizar.

    Prioridad:
    1. Variable DJANGO_SETTINGS_MODULE en .env
    2. Constante DEFAULT_SETTINGS (config.settings.dev)
    """
    try:
        module_path = config("DJANGO_SETTINGS_MODULE", default=DEFAULT_SETTINGS)
    except UndefinedValueError as exc:
        # No debería ocurrir gracias al default, pero lo manejamos igual
        raise RuntimeError(
            "⚠️  Falta la variable DJANGO_SETTINGS_MODULE en .env "
            "y no existe configuración por defecto.",
        ) from exc

    try:
        importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"❌ No se pudo importar el módulo de ajustes '{module_path}'.\n"
            "Verifica la ruta o crea el archivo correspondiente.",
        ) from exc

    return module_path


# -----------------------------------------------------------------------------
# 3.  Función principal
# -----------------------------------------------------------------------------
def main() -> None:
    """Punto de entrada para todos los comandos manage.py."""
    # 3.1 Resolver ajustes y exponer en el entorno
    try:
        settings_module = _resolve_settings_module()
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)
    except RuntimeError as err:
        print(err, file=sys.stderr)
        sys.exit(1)  # error de usuario / proyecto

    # 3.2 Importar el runner de Django
    try:
        from django.core.management import execute_from_command_line
    except ImportError as err:
        print(
            "❌ Django no está instalado o el entorno virtual está inactivo.\n"
            "Activa el venv e instala dependencias:\n"
            "    $ source venv/bin/activate\n"
            "    $ pip install -r requirements.txt",
            file=sys.stderr,
        )
        sys.exit(2)  # error de entorno

    # 3.3 Ejecutar comando solicitado
    try:
        execute_from_command_line(sys.argv)
    except KeyboardInterrupt:
        print("\n⏹️  Operación cancelada por el usuario.")
        sys.exit(0)
    except Exception as err:  # noqa: BLE001 – capturamos para salir con código 1
        print(f"❗ Error no controlado:\n{err}", file=sys.stderr)
        sys.exit(1)


# -----------------------------------------------------------------------------
# 4.  Bootstrap
# -----------------------------------------------------------------------------
if __name__ == "__main__":  # pragma: no cover
    main()
