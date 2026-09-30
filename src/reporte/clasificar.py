"""Responde las dudas pendientes de clasificacion (data/pendientes.json) y las guarda en la BBDD.

Uso:  python -m reporte.clasificar
Despues vuelve a correr el reporte: ya no gasta tokens para esos comercios.
"""
import json

from .categorizer import es_interactivo, preguntar
from .config import Config


def main() -> None:
    cfg = Config()
    path = cfg.data_dir / "pendientes.json"
    pendientes = json.loads(path.read_text()) if path.exists() else []
    if not pendientes:
        print("No hay clasificaciones pendientes.")
        return
    if not es_interactivo():
        raise SystemExit("Ejecuta este comando en una terminal interactiva.")
    n = preguntar(cfg, pendientes)
    print(f"\n{n} clasificacion(es) guardadas. Vuelve a generar el reporte para aplicarlas.")


if __name__ == "__main__":
    main()
