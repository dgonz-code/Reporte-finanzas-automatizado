"""Logica de negocio compartida por la consola (main.py) y la interfaz grafica (app.py)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import analyzer, categorizer, report_pdf, store
from .card_parser import parse_card_statement
from .config import Config
from .llm import UsageLog


@dataclass
class Resultado:
    periodo: str
    meta: dict
    movs: list
    agg: dict
    insights: dict
    pdf: Path
    log: UsageLog = field(default_factory=UsageLog)
    cuenta: dict | None = None
    tarjeta: dict | None = None
    pendientes: list = field(default_factory=list)


def latest_file(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True) if folder.exists() else []
    return files[0] if files else None


def _client(cfg: Config, use_llm: bool):
    if use_llm and cfg.llm == "api":
        import anthropic

        return anthropic.Anthropic()
    return None


def _load_account(path: Path, cfg: Config, client, log: UsageLog, use_llm: bool, say) -> dict:
    """Parser determinista primero ($0); la IA solo si el formato no se reconoce o no cuadra."""
    from . import account_parser

    data = None
    try:
        data = account_parser.parse_account_statement(path, cfg.pdf_password)
        if data["valido"]:
            return data
        say("AVISO: la cartola no cuadra con sus totales declarados.")
    except Exception as e:  # formato distinto, clave incorrecta, etc.
        say(f"AVISO: no se pudo leer la cartola con el parser determinista ({e}).")
    if not use_llm:
        if data:
            return data
        raise RuntimeError("No se pudo leer la cuenta corriente (revisa la clave del PDF). Sin IA activada no hay respaldo.")
    say("Usando la IA como respaldo para leer la cuenta corriente.")
    return analyzer.extract_account(client, cfg, log, account_parser.extract_text(path, cfg.pdf_password))


def _periodo(cuenta, tarjeta, movs) -> str:
    if tarjeta and tarjeta.get("fecha_estado"):
        return tarjeta["fecha_estado"][:7]
    if cuenta and cuenta.get("periodo"):
        return cuenta["periodo"]
    return max(m["fecha"] for m in movs)[:7]


def _meta(periodo, cuenta, tarjeta) -> dict:
    return {"periodo": periodo, "moneda": "CLP",
            "banco": " + ".join(filter(None, [cuenta and f"Cuenta corriente {cuenta['banco']}", tarjeta and f"Tarjeta {tarjeta['tarjeta']}"]))}


def _finalizar(cfg, use_llm, client, log, movs, cuenta, tarjeta, pendientes) -> Resultado:
    agg = analyzer.aggregate(movs, cuenta, tarjeta, pendientes)
    periodo = _periodo(cuenta, tarjeta, movs)
    meta = _meta(periodo, cuenta, tarjeta)
    insights = analyzer.generate_insights(client, cfg, log, meta, agg) if use_llm else analyzer.basic_insights(agg)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    pdf = cfg.output_dir / f"reporte-{periodo}.pdf"
    report_pdf.build_pdf(pdf, meta, agg, insights)
    store.save_month(cfg.data_dir, periodo, movs, agg, cuenta, tarjeta)
    return Resultado(periodo, meta, movs, agg, insights, pdf, log, cuenta, tarjeta, pendientes)


def procesar(cuenta_pdf: Path | None, tarjeta_xls: Path | None, cfg: Config, use_llm: bool = False,
             preguntar: bool = False, sheets: bool = False, say=print) -> Resultado:
    if not (cuenta_pdf or tarjeta_xls):
        raise ValueError("Indica al menos la cuenta corriente o la tarjeta.")
    log = UsageLog()
    client = _client(cfg, use_llm)

    movs, cuenta, tarjeta = [], None, None
    if tarjeta_xls:
        tarjeta = parse_card_statement(tarjeta_xls)
        movs += [{**m, "fuente": "tarjeta_credito"} for m in tarjeta["movimientos"]]
    if cuenta_pdf:
        cuenta = _load_account(cuenta_pdf, cfg, client, log, use_llm, say)
        movs += [{**m, "fuente": "cuenta_corriente"} for m in cuenta["movimientos"]]

    if sheets:
        from . import sheets_client

        n = categorizer.aplicar_correcciones(cfg, sheets_client.pull_corrections(cfg))
        if n:
            say(f"{n} correccion(es) aprendidas desde la pestana 'Clasificar' de Google Sheets.")

    pendientes = categorizer.categorize(movs, cfg, client, log, use_llm, use_web=cfg.use_web,
                                        titular=cuenta and cuenta.get("titular"))
    if preguntar and pendientes:
        if categorizer.es_interactivo():
            categorizer.preguntar(cfg, pendientes, movs)
            pendientes = []
        else:
            say("AVISO: --preguntar requiere una terminal interactiva; las dudas quedan en data/pendientes.json.")
    return _finalizar(cfg, use_llm, client, log, movs, cuenta, tarjeta, pendientes)


def meses_guardados(cfg: Config) -> list[str]:
    return sorted(p.name for p in cfg.data_dir.glob("20??-??") if (p / "movimientos.json").exists()) if cfg.data_dir.exists() else []


def recalcular_mes(cfg: Config, periodo: str, use_llm: bool = False) -> Resultado:
    """Vuelve a clasificar y a generar el reporte de un mes ya cargado, sin volver a subir las cartolas.

    Sirve despues de corregir categorias, o para pedirle sugerencias a la IA sobre las dudas.
    """
    d = cfg.data_dir / periodo
    movs = json.loads((d / "movimientos.json").read_text())
    fuentes = json.loads((d / "fuentes.json").read_text()) if (d / "fuentes.json").exists() else {}
    cuenta, tarjeta = fuentes.get("cuenta"), fuentes.get("tarjeta")
    log = UsageLog()
    client = _client(cfg, use_llm)
    pendientes = categorizer.categorize(movs, cfg, client, log, use_llm, use_web=cfg.use_web, titular=cuenta and cuenta.get("titular"))
    return _finalizar(cfg, use_llm, client, log, movs, cuenta, tarjeta, pendientes)


def cargar_comercios(cfg: Config, periodo: str) -> list[dict]:
    """Un renglon por comercio del mes guardado (para la pantalla Clasificar). No usa IA."""
    movs = json.loads((cfg.data_dir / periodo / "movimientos.json").read_text())
    fuentes = json.loads((cfg.data_dir / periodo / "fuentes.json").read_text()) if (cfg.data_dir / periodo / "fuentes.json").exists() else {}
    cuenta = fuentes.get("cuenta")
    pendientes = categorizer.categorize(movs, cfg, None, UsageLog(), use_llm=False, use_web=False, titular=cuenta and cuenta.get("titular"))
    return categorizer.comercios_resumen(movs, cfg, pendientes)
