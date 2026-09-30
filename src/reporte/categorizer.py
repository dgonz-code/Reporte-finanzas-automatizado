"""Categoriza movimientos minimizando llamadas al LLM.

Orden: (1) reglas por palabra clave -> (2) cache de comercios ya clasificados ->
(3) un solo llamado a Claude con las descripciones unicas que quedaron sin categoria.
El resultado del paso 3 se guarda en el cache, asi cada comercio se paga una sola vez.
"""
import json
import re
from pathlib import Path

from .config import Config
from .llm import UsageLog, ask

CATEGORIAS = [
    "Supermercado", "Restaurantes y delivery", "Transporte y bencina", "Vivienda y cuentas basicas",
    "Salud", "Educacion", "Entretenimiento y suscripciones", "Compras y retail", "Hogar y ferreteria",
    "Mascotas", "Viajes", "Seguros", "Deuda y creditos", "Comisiones e intereses bancarios",
    "Pagos digitales sin detalle", "Transferencias enviadas", "Sueldo e ingresos",
    "Transferencias recibidas", "Ahorro e inversion", "Pago tarjeta (interno)", "Otros",
]
INTERNO = "Pago tarjeta (interno)"  # no es gasto: se paga la tarjeta desde la cuenta corriente
INGRESOS = {"Sueldo e ingresos", "Transferencias recibidas"}

RULES_FILE = Path(__file__).with_name("reglas_categorias.json")

SCHEMA = {
    "type": "object",
    "properties": {
        "categorias": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "categoria": {"type": "string", "enum": CATEGORIAS}},
                "required": ["id", "categoria"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["categorias"],
    "additionalProperties": False,
}


def norm(desc: str) -> str:
    d = desc.upper()
    d = re.sub(r"TASA INT.*$", "", d)
    d = re.sub(r"\d{6,}K?", "", d)  # ruts / ids de comercio
    return re.sub(r"\s+", " ", d).strip()


def _by_rules(key: str, rules: list[list[str]]) -> str | None:
    return next((cat for kw, cat in rules if kw in key), None)


def categorize(movs: list[dict], cfg: Config, client, log: UsageLog, use_llm: bool = True) -> list[str]:
    """Asigna m['categoria'] a cada movimiento. Devuelve descripciones que quedaron en 'Otros' sin LLM."""
    rules = json.loads(RULES_FILE.read_text())["reglas"]
    cache_path = cfg.data_dir / "merchant_cache.json"
    cache: dict[str, str] = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    pending: dict[str, str] = {}
    for m in movs:
        if m.get("tipo") == "pago_tarjeta":
            m["categoria"] = INTERNO
            continue
        key = norm(m["descripcion"])
        cat = _by_rules(key, rules) or cache.get(key)
        if cat:
            m["categoria"] = cat
        else:
            m["categoria"] = "Otros"
            pending[key] = m["descripcion"]

    if pending and use_llm and client is not None:
        keys = list(pending)
        listing = "\n".join(f"{i}: {pending[k]} (monto ejemplo: {next(abs(m['monto']) for m in movs if norm(m['descripcion']) == k):.0f})" for i, k in enumerate(keys))
        res = ask(
            client, cfg, log, "categorizar",
            "Clasificas movimientos bancarios chilenos en las categorias permitidas. "
            "Si no puedes identificar el comercio, usa 'Otros'. Responde un item por id.",
            listing, SCHEMA, max_tokens=4000,
        )
        for item in res["categorias"]:
            if 0 <= item["id"] < len(keys):
                cache[keys[item["id"]]] = item["categoria"]
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True))
        for m in movs:
            if m["categoria"] == "Otros":
                m["categoria"] = cache.get(norm(m["descripcion"]), "Otros")
        pending = {k: v for k, v in pending.items() if cache.get(k, "Otros") == "Otros"}

    return sorted(set(pending.values()))
