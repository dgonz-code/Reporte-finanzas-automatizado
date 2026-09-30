"""Guarda cada mes normalizado en data/AAAA-MM/ para tendencias y comparativas futuras."""
import json
from pathlib import Path


def save_month(data_dir: Path, periodo_iso: str, movs: list[dict], agg: dict) -> Path:
    d = data_dir / periodo_iso
    d.mkdir(parents=True, exist_ok=True)
    (d / "movimientos.json").write_text(json.dumps(movs, ensure_ascii=False, indent=1))
    resumen = {k: v for k, v in agg.items() if k != "mayores_gastos"}
    (d / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1))
    return d
