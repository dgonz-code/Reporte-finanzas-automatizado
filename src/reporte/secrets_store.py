"""Claves en el Llavero de macOS (via keyring). Nunca en archivos ni en el repositorio."""
from __future__ import annotations

SERVICE = "reporte-finanzas"


def get(name: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(SERVICE, name)
    except BaseException as e:  # sin backend de llavero (incluye fallos nativos que no heredan de Exception)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return None


def put(name: str, value: str) -> bool:
    try:
        import keyring

        keyring.set_password(SERVICE, name, value)
        return True
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return False


def delete(name: str) -> None:
    try:
        import keyring

        keyring.delete_password(SERVICE, name)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
