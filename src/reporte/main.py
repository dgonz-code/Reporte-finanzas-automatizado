"""Flujo: cuenta corriente (PDF) + tarjeta (XLS) -> categorias -> reporte PDF -> (Google Sheets) -> correo.

Por defecto NO usa IA ($0). Activala con REPORTE_LLM=claude-code (tu plan) o REPORTE_LLM=api (se paga aparte).

Uso:
  python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send
  python -m reporte.main --cuenta ... --tarjeta ... --preguntar --no-send     # te consulta las dudas
  python -m reporte.main --tarjeta entrada/tarjeta.xls --no-send              # sin IA, $0
  python -m reporte.main --sheets                                             # cuenta desde Gmail, tarjeta desde entrada/
"""
import argparse
from pathlib import Path

import anthropic

from . import analyzer, categorizer, report_pdf, store
from .card_parser import parse_card_statement
from .config import Config
from .llm import UsageLog


def _load_account(path: Path, cfg: Config, client, log: UsageLog, use_llm: bool) -> dict:
    """Parser determinista primero ($0); el LLM solo si el formato no se reconoce o no cuadra."""
    from . import account_parser

    data = None
    try:
        data = account_parser.parse_account_statement(path, cfg.pdf_password)
        if data["valido"]:
            return data
        print("AVISO: la cartola no cuadra con sus totales declarados.")
    except Exception as e:  # formato distinto, clave incorrecta, etc.
        print(f"AVISO: no se pudo leer la cartola con el parser determinista ({e}).")
    if not use_llm:
        if data:
            return data
        raise SystemExit("No se pudo leer la cuenta corriente sin LLM.")
    print("Usando el LLM como respaldo para la cuenta corriente.")
    return analyzer.extract_account(client, cfg, log, account_parser.extract_text(path, cfg.pdf_password))


def latest_file(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True) if folder.exists() else []
    return files[0] if files else None


def run(cuenta_pdf: Path | None, tarjeta_xls: Path | None, cfg: Config, send: bool, use_llm: bool,
        preguntar: bool = False, sheets: bool = False) -> Path:
    if not (cuenta_pdf or tarjeta_xls):
        raise SystemExit("Indica al menos --cuenta o --tarjeta.")
    log = UsageLog()
    client = anthropic.Anthropic() if use_llm and cfg.llm == "api" else None

    movs, cuenta, tarjeta = [], None, None
    if tarjeta_xls:
        tarjeta = parse_card_statement(tarjeta_xls)
        movs += [{**m, "fuente": "tarjeta_credito"} for m in tarjeta["movimientos"]]
    if cuenta_pdf:
        cuenta = _load_account(cuenta_pdf, cfg, client, log, use_llm)
        movs += [{**m, "fuente": "cuenta_corriente"} for m in cuenta["movimientos"]]

    pendientes = categorizer.categorize(movs, cfg, client, log, use_llm, use_web=cfg.use_web, titular=cuenta and cuenta.get("titular"))
    if preguntar and pendientes:
        if categorizer.es_interactivo():
            categorizer.preguntar(cfg, pendientes, movs)
            pendientes = []
        else:
            print("AVISO: --preguntar requiere una terminal interactiva; las dudas quedan en data/pendientes.json.")
    agg = analyzer.aggregate(movs, cuenta, tarjeta, pendientes)

    if tarjeta and tarjeta["fecha_estado"]:
        periodo_iso = tarjeta["fecha_estado"][:7]
    elif cuenta:
        periodo_iso = cuenta.get("periodo") or max(m["fecha"] for m in movs)[:7]
    else:
        periodo_iso = max(m["fecha"] for m in movs)[:7]
    meta = {"periodo": periodo_iso, "moneda": "CLP",
            "banco": " + ".join(filter(None, [cuenta and f"Cuenta corriente {cuenta['banco']}", tarjeta and f"Tarjeta {tarjeta['tarjeta']}"]))}
    insights = analyzer.generate_insights(client, cfg, log, meta, agg) if use_llm else analyzer.basic_insights(agg)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / f"reporte-{periodo_iso}.pdf"
    report_pdf.build_pdf(out, meta, agg, insights)
    store.save_month(cfg.data_dir, periodo_iso, movs, agg)

    print(f"Reporte: {out}\nDatos guardados en {cfg.data_dir / periodo_iso}")
    if sheets:
        from . import sheets_client

        print("Google Sheets:", sheets_client.save_month(cfg, periodo_iso, movs, agg))
    print(f"Ingresos {agg['ingresos']:,.0f} | Gastos {agg['gastos']:,.0f} (cuenta {agg['gastos_cuenta_corriente']:,.0f} + tarjeta {agg['gastos_tarjeta']:,.0f})")
    for k, v in agg["conciliacion"].items():
        print(f"Conciliacion {k}: {'OK' if not v else f'DIFERENCIA {v:,.0f} -> revisar extraccion'}")
    if pendientes:
        print(f"{len(pendientes)} clasificaciones con duda (total ${sum(p['total'] for p in pendientes):,.0f}). "
              "Responde con: python -m reporte.clasificar")
    print(log.summary(cfg))

    if send:
        from . import gmail_client

        gmail_client.send_report(cfg, f"Reporte financiero - {periodo_iso}", report_pdf.build_email_html(meta, agg, insights), out)
        print("Correo enviado.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuenta", type=Path, help="PDF de cuenta corriente (local). Sin esto se baja de Gmail")
    ap.add_argument("--tarjeta", type=Path, help="XLS de tarjeta (local). Sin esto se toma el mas reciente de la carpeta de entrada")
    ap.add_argument("--no-send", action="store_true", help="No enviar el correo")
    ap.add_argument("--sheets", action="store_true", help="Guardar tambien en Google Sheets")
    ap.add_argument("--sin-llm", action="store_true", help="Forzar modo sin IA aunque REPORTE_LLM este activo")
    ap.add_argument("--preguntar", action="store_true", help="Pregunta por consola las clasificaciones dudosas")
    args = ap.parse_args()
    cfg = Config()

    cuenta, tarjeta = args.cuenta, args.tarjeta
    if not tarjeta:
        tarjeta = latest_file(cfg.inbox_dir, cfg.inbox_card_glob)
        print(f"Tarjeta: {tarjeta}" if tarjeta else f"AVISO: no hay .xls de tarjeta en {cfg.inbox_dir}/ (se sigue solo con la cuenta corriente).")
    if not cuenta:
        if cfg.credentials_file.exists() or cfg.token_file.exists():
            from . import gmail_client

            cuenta = gmail_client.download_statement(cfg, cfg.output_dir / "inbox", cfg.gmail_query_cuenta, (".pdf",))
        else:
            cuenta = latest_file(cfg.inbox_dir, "*.pdf")
            print(f"Sin Gmail configurado; cuenta corriente desde carpeta: {cuenta}")
    use_llm = cfg.llm != "none" and not args.sin_llm
    run(cuenta, tarjeta, cfg, send=not args.no_send, use_llm=use_llm, preguntar=args.preguntar, sheets=args.sheets)


if __name__ == "__main__":
    main()
