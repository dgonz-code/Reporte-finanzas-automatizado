"""Usa Claude para extraer movimientos de la cartola y redactar hallazgos.

Los calculos (totales, categorias, conciliacion de saldos) se hacen en Python;
Claude solo interpreta el texto y escribe el analisis.
"""
import json
from collections import defaultdict

import anthropic

from .config import Config

CATEGORIAS = [
    "Supermercado", "Restaurantes y delivery", "Transporte y bencina", "Vivienda y cuentas basicas",
    "Salud", "Educacion", "Entretenimiento y suscripciones", "Compras y retail",
    "Viajes", "Comisiones e intereses bancarios", "Transferencias enviadas",
    "Sueldo e ingresos", "Transferencias recibidas", "Ahorro e inversion", "Otros",
]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "banco": {"type": "string"},
        "periodo": {"type": "string", "description": "Ej: 'Agosto 2026'"},
        "moneda": {"type": "string"},
        "saldo_inicial": {"type": ["number", "null"]},
        "saldo_final": {"type": ["number", "null"]},
        "movimientos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                    "descripcion": {"type": "string"},
                    "monto": {"type": "number", "description": "Negativo = cargo/gasto, positivo = abono/ingreso"},
                    "categoria": {"type": "string", "enum": CATEGORIAS},
                },
                "required": ["fecha", "descripcion", "monto", "categoria"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["banco", "periodo", "moneda", "saldo_inicial", "saldo_final", "movimientos"],
    "additionalProperties": False,
}

INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {
        "resumen_ejecutivo": {"type": "string"},
        "hallazgos": {"type": "array", "items": {"type": "string"}},
        "alertas": {"type": "array", "items": {"type": "string"}},
        "recomendaciones": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["resumen_ejecutivo", "hallazgos", "alertas", "recomendaciones"],
    "additionalProperties": False,
}


def _ask(client: anthropic.Anthropic, cfg: Config, system: str, user: str, schema: dict) -> dict:
    with client.messages.stream(
        model=cfg.model,
        max_tokens=32000,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError("El modelo rechazo la solicitud.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("La respuesta se trunco; la cartola es demasiado larga para una sola pasada.")
    text = next(b.text for b in msg.content if b.type == "text")
    return json.loads(text)


def extract_statement(client: anthropic.Anthropic, cfg: Config, statement_text: str) -> dict:
    system = (
        "Eres un asistente que extrae datos de cartolas bancarias chilenas. "
        "Extrae TODOS los movimientos sin omitir ninguno y sin inventar datos. "
        "Los montos van en numeros sin separadores de miles; cargos negativos, abonos positivos. "
        "Clasifica cada movimiento en una de las categorias permitidas."
    )
    return _ask(client, cfg, system, f"Cartola:\n\n{statement_text}", EXTRACTION_SCHEMA)


def aggregate(data: dict) -> dict:
    movs = data["movimientos"]
    ingresos = sum(m["monto"] for m in movs if m["monto"] > 0)
    gastos = -sum(m["monto"] for m in movs if m["monto"] < 0)
    by_cat: dict[str, float] = defaultdict(float)
    by_desc: dict[str, list[float]] = defaultdict(list)
    for m in movs:
        if m["monto"] < 0:
            by_cat[m["categoria"]] += -m["monto"]
            by_desc[m["descripcion"].strip().upper()].append(-m["monto"])

    si, sf = data.get("saldo_inicial"), data.get("saldo_final")
    diferencia = None
    if si is not None and sf is not None:
        diferencia = round((si + ingresos - gastos) - sf, 2)  # != 0 => movimientos faltantes o mal leidos

    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "balance": ingresos - gastos,
        "tasa_ahorro": (ingresos - gastos) / ingresos if ingresos else None,
        "gastos_por_categoria": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "mayores_gastos": sorted((m for m in movs if m["monto"] < 0), key=lambda m: m["monto"])[:10],
        "comercios_recurrentes": {d: {"veces": len(v), "total": sum(v)} for d, v in by_desc.items() if len(v) > 1},
        "diferencia_conciliacion": diferencia,
        "n_movimientos": len(movs),
    }


def generate_insights(client: anthropic.Anthropic, cfg: Config, data: dict, agg: dict) -> dict:
    system = (
        "Eres un asesor financiero personal. Escribes en espanol claro y directo. "
        "Basate SOLO en los datos entregados; no inventes cifras. Se concreto: menciona montos y categorias. "
        "Si diferencia_conciliacion no es 0 o null, incluyelo como alerta de calidad de datos."
    )
    payload = {k: data[k] for k in ("banco", "periodo", "moneda")} | {"agregados": agg}
    return _ask(client, cfg, system, json.dumps(payload, ensure_ascii=False, indent=1), INSIGHTS_SCHEMA)
