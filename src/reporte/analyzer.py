"""Extraccion (solo cuenta corriente), agregados en Python e insights con Claude.

Los calculos (totales, categorias, conciliacion) se hacen en Python; Claude solo
interpreta el PDF de la cuenta corriente y redacta el analisis sobre numeros ya calculados.
"""
import json
from collections import defaultdict

from .categorizer import INGRESOS, INTERNO, norm
from .llm import ask

ACCOUNT_SCHEMA = {
    "type": "object",
    "properties": {
        "banco": {"type": "string"},
        "periodo": {"type": "string", "description": "Ej: 'Agosto 2026'"},
        "saldo_inicial": {"type": ["number", "null"]},
        "saldo_final": {"type": ["number", "null"]},
        "movimientos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fecha": {"type": "string", "description": "YYYY-MM-DD"},
                    "descripcion": {"type": "string"},
                    "monto": {"type": "number", "description": "Negativo = cargo, positivo = abono"},
                },
                "required": ["fecha", "descripcion", "monto"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["banco", "periodo", "saldo_inicial", "saldo_final", "movimientos"],
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


def extract_account(client, cfg, log, text: str) -> dict:
    system = (
        "Extraes movimientos de cartolas de cuenta corriente chilenas. Incluye TODOS los movimientos, "
        "sin omitir ni inventar. Montos como numeros sin separadores de miles; cargos negativos, abonos positivos. "
        "No incluyas filas de saldo ni totales."
    )
    data = ask(client, cfg, log, "extraer cuenta cte", system, f"Cartola:\n\n{text}", ACCOUNT_SCHEMA, max_tokens=32000)
    data.update(fuente="cuenta_corriente", moneda="CLP")
    return data


def aggregate(movs: list[dict], cuenta: dict | None = None, tarjeta: dict | None = None) -> dict:
    """movs: movimientos ya categorizados (monto<0 = gasto)."""
    ingresos = 0.0
    by_cat: dict[str, float] = defaultdict(float)
    by_desc: dict[str, list[float]] = defaultdict(list)
    for m in movs:
        cat = m["categoria"]
        if cat == INTERNO:
            continue
        if cat in INGRESOS:
            ingresos += m["monto"]
            continue
        by_cat[cat] += -m["monto"]  # reembolsos (monto>0) restan del gasto de su categoria
        if m["monto"] < 0:
            by_desc[norm(m["descripcion"])].append(-m["monto"])

    gastos = sum(by_cat.values())
    gastos_cuenta = -sum(m["monto"] for m in movs if m.get("fuente") == "cuenta_corriente" and m["categoria"] not in INGRESOS | {INTERNO})
    gastos_tarjeta = -sum(m["monto"] for m in movs if m.get("fuente") == "tarjeta_credito" and m["categoria"] != INTERNO)

    concil = {}
    if cuenta and cuenta.get("saldo_inicial") is not None and cuenta.get("saldo_final") is not None:
        net = sum(m["monto"] for m in movs if m.get("fuente") == "cuenta_corriente")
        concil["cuenta_corriente"] = round(cuenta["saldo_inicial"] + net - cuenta["saldo_final"], 2)
    if tarjeta and tarjeta.get("total_facturado_declarado") is not None:
        net = -sum(m["monto"] for m in movs if m.get("fuente") == "tarjeta_credito" and m["categoria"] != INTERNO)
        concil["tarjeta"] = round(net - tarjeta["total_facturado_declarado"], 2)

    gasto_movs = [m for m in movs if m["monto"] < 0 and m["categoria"] != INTERNO and m["categoria"] not in INGRESOS]
    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "gastos_cuenta_corriente": gastos_cuenta,
        "gastos_tarjeta": gastos_tarjeta,
        "balance": ingresos - gastos,
        "tasa_ahorro": (ingresos - gastos) / ingresos if ingresos else None,
        "gastos_por_categoria": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
        "mayores_gastos": sorted(gasto_movs, key=lambda m: m["monto"])[:10],
        "comercios_recurrentes": {d: {"veces": len(v), "total": sum(v)} for d, v in by_desc.items() if len(v) > 1 and d},
        "conciliacion": concil,  # distinto de 0 => movimientos faltantes o mal leidos
        "n_movimientos": len(movs),
        "cuotas_por_vencer": (tarjeta or {}).get("cuotas_por_vencer", {}),
        "sin_categorizar": sum(1 for m in movs if m["categoria"] == "Otros"),
    }


def _clp(x: float) -> str:
    return f"${x:,.0f}".replace(",", ".")


def basic_insights(agg: dict) -> dict:
    """Version sin LLM ($0): datos duros, sin redaccion."""
    top = list(agg["gastos_por_categoria"].items())[:3]
    return {
        "resumen_ejecutivo": (
            f"Ingresos {_clp(agg['ingresos'])}, gastos {_clp(agg['gastos'])}, balance {_clp(agg['balance'])}. "
            "(Modo sin LLM: sin analisis redactado.)"
        ),
        "hallazgos": [f"{k}: {_clp(v)}" for k, v in top],
        "alertas": [f"Conciliacion {k}: diferencia {v}" for k, v in agg["conciliacion"].items() if v],
        "recomendaciones": [],
    }


def generate_insights(client, cfg, log, meta: dict, agg: dict) -> dict:
    system = (
        "Eres un asesor financiero personal. Escribes en espanol claro y directo. Basate SOLO en los datos entregados; "
        "no inventes cifras. Se concreto: menciona montos y categorias. Las categorias 'Pagos digitales sin detalle' y 'Otros' "
        "son gasto sin identificar: mencionalo si pesan. 'cuotas_por_vencer' son compromisos futuros de la tarjeta. "
        "Si una conciliacion es distinta de 0, agregala como alerta de calidad de datos."
    )
    payload = {**meta, "agregados": {k: v for k, v in agg.items() if k != "mayores_gastos"},
               "mayores_gastos": [{k: m[k] for k in ("fecha", "descripcion", "monto", "categoria")} for m in agg["mayores_gastos"][:5]]}
    return ask(client, cfg, log, "insights", system, json.dumps(payload, ensure_ascii=False), INSIGHTS_SCHEMA, max_tokens=3000)
