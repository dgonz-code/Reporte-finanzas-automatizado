"""Guarda los datos de cada mes en una planilla de Google Sheets (la 'tabla' para tendencias y presupuesto).

Pestanas:
  Movimientos  una fila por movimiento           (periodo, fecha, fuente, descripcion, monto, categoria, tipo)
  Resumen      una fila por mes                  (ingresos, gastos, balance, tasa de ahorro...)
  Categorias   formato largo: periodo, categoria, gasto   (ideal para tablas dinamicas y graficos)
  Presupuesto  categoria, presupuesto mensual    (la llenas tu; queda lista para comparar)

  Clasificar   un renglon por comercio: ahi ENSENAS y CORRIGES eligiendo la categoria en la columna 'corregir_a'

Es idempotente: volver a correr el mismo mes reemplaza sus filas, no las duplica.
"""
from __future__ import annotations

from .config import Config

TABS = {
    "Movimientos": ["periodo", "fecha", "fuente", "descripcion", "monto", "categoria", "tipo"],
    "Resumen": ["periodo", "ingresos", "gastos", "gastos_cuenta_corriente", "gastos_tarjeta", "balance",
                "tasa_ahorro", "n_movimientos", "sin_categorizar", "clasificaciones_con_duda"],
    "Categorias": ["periodo", "categoria", "gasto"],
    "Presupuesto": ["categoria", "presupuesto_mensual"],
}


def _service(cfg: Config):
    from googleapiclient.discovery import build  # import perezoso: solo si se usa Sheets

    from . import google_auth

    return build("sheets", "v4", credentials=google_auth.credentials(cfg))


def ensure_spreadsheet(svc, cfg: Config) -> str:
    """Usa REPORTE_SHEET_ID, o crea la planilla la primera vez y recuerda su id en data/sheet_id.txt."""
    if cfg.sheet_id:
        return cfg.sheet_id
    memo = cfg.data_dir / "sheet_id.txt"
    if memo.exists():
        return memo.read_text().strip()
    body = {"properties": {"title": "Finanzas personales"}, "sheets": [{"properties": {"title": t}} for t in TABS]}
    sid = svc.spreadsheets().create(body=body, fields="spreadsheetId").execute()["spreadsheetId"]
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    memo.write_text(sid)
    return sid


CLASIFICAR = "Clasificar"
CLASIFICAR_HEADER = ["estado", "comercio", "monto_mes", "categoria_actual", "fuente", "corregir_a", "clave"]


def _ensure_tabs(svc, sid: str) -> None:
    have = {s["properties"]["title"] for s in svc.spreadsheets().get(spreadsheetId=sid).execute()["sheets"]}
    missing = [t for t in [*TABS, CLASIFICAR] if t not in have]
    if missing:
        svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{"addSheet": {"properties": {"title": t}}} for t in missing]}).execute()


def _replace_period(svc, sid: str, tab: str, periodo: str, rows: list[list]) -> None:
    """Quita las filas del periodo y agrega las nuevas (RAW: 'YYYY-MM' se mantiene como texto)."""
    got = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{tab}!A:Z").execute().get("values", [])
    header = TABS[tab]
    kept = [r for r in got[1:] if r and r[0] != periodo] if got else []
    table = [header] + kept + rows
    svc.spreadsheets().values().clear(spreadsheetId=sid, range=f"{tab}!A:Z").execute()
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"{tab}!A1", valueInputOption="RAW", body={"values": table}).execute()


def save_month(cfg: Config, periodo: str, movs: list[dict], agg: dict, svc=None) -> str:
    svc = svc or _service(cfg)
    sid = ensure_spreadsheet(svc, cfg)
    _ensure_tabs(svc, sid)

    _replace_period(svc, sid, "Movimientos", periodo, [
        [periodo, m["fecha"], m.get("fuente", ""), m["descripcion"], m["monto"], m["categoria"], m.get("tipo", "")] for m in movs
    ])
    _replace_period(svc, sid, "Resumen", periodo, [[
        periodo, agg["ingresos"], agg["gastos"], agg["gastos_cuenta_corriente"], agg["gastos_tarjeta"], agg["balance"],
        round(agg["tasa_ahorro"], 4) if agg["tasa_ahorro"] is not None else "", agg["n_movimientos"],
        agg["sin_categorizar"], len(agg["pendientes"]),
    ]])
    _replace_period(svc, sid, "Categorias", periodo, [[periodo, c, v] for c, v in agg["gastos_por_categoria"].items()])

    if not svc.spreadsheets().values().get(spreadsheetId=sid, range="Presupuesto!A1:A1").execute().get("values"):
        svc.spreadsheets().values().update(spreadsheetId=sid, range="Presupuesto!A1", valueInputOption="RAW",
                                           body={"values": [TABS["Presupuesto"]]}).execute()
    return f"https://docs.google.com/spreadsheets/d/{sid}"


def pull_corrections(cfg: Config, svc=None) -> list[dict]:
    """Lee lo que elegiste en la columna 'corregir_a' de la pestana Clasificar (antes de clasificar el mes)."""
    sid = cfg.sheet_id or ((cfg.data_dir / "sheet_id.txt").read_text().strip() if (cfg.data_dir / "sheet_id.txt").exists() else None)
    if not sid:
        return []
    svc = svc or _service(cfg)
    rows = svc.spreadsheets().values().get(spreadsheetId=sid, range=f"{CLASIFICAR}!A:G").execute().get("values", [])
    out = []
    for r in rows[1:]:
        r = r + [""] * (len(CLASIFICAR_HEADER) - len(r))
        d = dict(zip(CLASIFICAR_HEADER, r))
        if d["corregir_a"].strip():
            out.append({"clave": d["clave"], "comercio": d["comercio"], "corregir_a": d["corregir_a"].strip()})
    return out


def push_comercios(cfg: Config, comercios: list[dict], categorias: list[str], svc=None) -> None:
    """Reescribe la pestana Clasificar con el estado actual y deja un desplegable de categorias en 'corregir_a'."""
    svc = svc or _service(cfg)
    sid = ensure_spreadsheet(svc, cfg)
    _ensure_tabs(svc, sid)
    table = [CLASIFICAR_HEADER] + [[c["estado"], c["comercio"], c["monto"], c["categoria"], c["fuente"], "", c["clave"]] for c in comercios]
    svc.spreadsheets().values().clear(spreadsheetId=sid, range=f"{CLASIFICAR}!A:G").execute()
    svc.spreadsheets().values().update(spreadsheetId=sid, range=f"{CLASIFICAR}!A1", valueInputOption="RAW", body={"values": table}).execute()
    tab = next(s["properties"] for s in svc.spreadsheets().get(spreadsheetId=sid).execute()["sheets"] if s["properties"]["title"] == CLASIFICAR)
    svc.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [{
        "setDataValidation": {
            "range": {"sheetId": tab["sheetId"], "startRowIndex": 1, "endRowIndex": max(len(table), 2), "startColumnIndex": 5, "endColumnIndex": 6},
            "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": c} for c in categorias]},
                     "showCustomUi": True, "strict": True},
        }
    }]}).execute()
