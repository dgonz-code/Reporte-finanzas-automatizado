"""Programa la ejecucion automatica en macOS (LaunchAgent). Uso:  python -m reporte.launchd instalar|desinstalar"""
from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "cl.finanzas.reporte"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
DIAS = range(2, 9)  # dias 2 al 8 de cada mes, 09:30; si ya se proceso o aun falta algo, no hace nada


def plist_dict(python: str, proyecto: Path, hora: int = 9, minuto: int = 30) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "reporte.automatico"],
        "WorkingDirectory": str(proyecto),
        "EnvironmentVariables": {"PYTHONPATH": str(proyecto / "src")},
        "StartCalendarInterval": [{"Day": d, "Hour": hora, "Minute": minuto} for d in DIAS],
        "StandardOutPath": str(proyecto / "data" / "automatico.log"),
        "StandardErrorPath": str(proyecto / "data" / "automatico.log"),
    }


def _launchctl(*args: str) -> int:
    return subprocess.run(["launchctl", *args], check=False).returncode


def instalar() -> None:
    if sys.platform != "darwin":
        raise SystemExit("Esto solo funciona en macOS.")
    proyecto = Path(__file__).resolve().parents[2]
    (proyecto / "data").mkdir(exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(plist_dict(sys.executable, proyecto)))
    uid = str(os.getuid())
    _launchctl("bootout", f"gui/{uid}/{LABEL}")  # si ya estaba instalado; ignora el error
    if _launchctl("bootstrap", f"gui/{uid}", str(PLIST)) != 0:
        raise SystemExit("No se pudo activar. Intenta cerrar sesion y volver a entrar, o revisa el archivo " + str(PLIST))
    print(f"Listo: el reporte se generara solo del dia 2 al 8 de cada mes a las 09:30.\nRegistro: {proyecto / 'data' / 'automatico.log'}")


def desinstalar() -> None:
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    PLIST.unlink(missing_ok=True)
    print("Automatizacion desactivada.")


if __name__ == "__main__":
    {"instalar": instalar, "desinstalar": desinstalar}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
