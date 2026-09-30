"""Guarda cada mes normalizado en data/AAAA-MM/ para tendencias y comparativas futuras."""
from __future__ import annotations

import json
from pathlib import Path


def save_month(data_dir: Path, periodo_iso: str, movs: list[dict], agg: dict, cuenta: dict | None = None, tarjeta: dict | None = None) -> Path:
    d = data_dir / periodo_iso
    d.mkdir(parents=True, exist_ok=True)
    (d / "movimientos.json").write_text(json.dumps(movs, ensure_ascii=False, indent=1))
    resumen = {k: v for k, v in agg.items() if k != "mayores_gastos"}
    (d / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    # Lo minimo para poder recalcular el mes (conciliacion, cuotas) sin volver a leer las cartolas.
    # Incluye el titular (solo local, en data/ que esta en .gitignore) para reconocer tus traspasos propios al recalcular.
    fuentes = {
        "cuenta": cuenta and {k: cuenta.get(k) for k in ("banco", "periodo", "saldo_inicial", "saldo_final", "titular")},
        "tarjeta": tarjeta and {k: tarjeta.get(k) for k in ("banco", "tarjeta", "fecha_estado", "total_facturado_declarado", "cuotas_por_vencer")},
    }
    (d / "fuentes.json").write_text(json.dumps(fuentes, ensure_ascii=False, indent=1))
    return d
