"""Parser determinista del estado de cuenta de tarjeta de credito Scotiabank (.xls).

No usa LLM: el archivo es una tabla con columnas fijas, asi la extraccion cuesta $0
y es exacta. El monto que se toma es "Cargo del Mes" (en cuotas = valor de la cuota).
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import xlrd

DATE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
CODE = re.compile(r"^\d{4} \d+$")
CUOTA = re.compile(r"^\d{2}/\d{2}$")
MONEY = re.compile(r"^\$\s*(-?[\d.]+)$")


def _money(s: str) -> float | None:
    m = MONEY.match(s.strip())
    return float(m.group(1).replace(".", "")) if m else None


def _iso(d: str) -> str:
    return datetime.strptime(d, "%d/%m/%Y").strftime("%Y-%m-%d")


def _classify_row(desc: str, cuota: str, monto: float) -> str:
    d = desc.upper()
    if monto < 0 and "PAGO" in d:
        return "pago_tarjeta"
    if "NOTA DE CREDITO" in d:
        return "ajuste"
    if any(k in d for k in ("IMPUESTO", "INTERES", "SERVICIO DE ACTIVIDAD", "TRASPASO DEUDA")):
        return "costo_financiero"
    if cuota and cuota[:2] != cuota[3:]:
        return "compra_en_cuotas"
    return "compra"


def parse_card_statement(path: Path) -> dict:
    sheet = xlrd.open_workbook(str(path)).sheet_by_index(0)
    rows = [[str(c).strip() for c in sheet.row_values(r) if str(c).strip()] for r in range(sheet.nrows)]
    flat = "\n".join(" | ".join(r) for r in rows)

    titular = next((c for r in rows for c in r if "VISA XXXX" in c), "")
    fecha_estado = re.search(r"(\d{2}/\d{2}/\d{4})\s*$", titular)
    total_fact = re.search(r"Monto Total Facturado a Pagar \$([\d.]+)", flat)
    periodo = re.search(r"Per[ií]odo de Facturaci[oó]n Anterior\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})", flat)

    movs = []
    for r in rows:
        di = next((i for i, c in enumerate(r) if DATE.match(c)), None)
        if di is None or di + 2 >= len(r) or not CODE.match(r[di + 1]):
            continue
        desc = r[di + 2]
        tail = r[di + 3:]
        cuota = next((c for c in tail if CUOTA.match(c)), "")
        amounts = [a for a in (_money(c) for c in tail) if a is not None]
        if not amounts:
            continue
        monto_op, cargo_mes = amounts[0], amounts[-1]
        movs.append({
            "fecha": _iso(r[di]),
            "descripcion": re.sub(r"\s+", " ", desc),
            "monto": -cargo_mes,  # convencion: gasto negativo, abono positivo
            "monto_operacion": monto_op,
            "cuota": cuota,
            "tipo": _classify_row(desc, cuota, cargo_mes),
            "lugar": r[0] if di > 0 else "",
        })

    venc = {}
    for i, r in enumerate(rows):
        if r[:1] == ["ACTUAL"] and i + 1 < len(rows):
            venc = {k: _money(v) for k, v in zip(r, rows[i + 1])}
            break

    ultimos4 = re.search(r"XXXX-(\d{4})", titular)
    ultimos4 = ultimos4.group(1) if ultimos4 else "????"

    estado_dt = fecha_estado.group(1) if fecha_estado else None
    return {
        "fuente": "tarjeta_credito",
        "banco": "Scotiabank",
        "tarjeta": f"VISA ****{ultimos4}",
        "fecha_estado": _iso(estado_dt) if estado_dt else None,
        "total_facturado_declarado": float(total_fact.group(1).replace(".", "")) if total_fact else None,
        "periodo_anterior": [periodo.group(1), periodo.group(2)] if periodo else None,
        "moneda": "CLP",
        "cuotas_por_vencer": venc,  # {"ACTUAL": .., "SEPTIEMBRE": ..}
        "movimientos": movs,
    }
