"""Flujo: cuenta corriente (PDF) + tarjeta (XLS) -> categorias -> reporte PDF -> (Google Sheets) -> correo.

Por defecto NO usa IA ($0). Activala con REPORTE_LLM=claude-code (tu plan) o REPORTE_LLM=api (se paga aparte).

Uso:
  python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send
  python -m reporte.main --cuenta ... --tarjeta ... --preguntar --no-send     # te consulta las dudas
  python -m reporte.main --tarjeta entrada/tarjeta.xls --no-send              # sin IA, $0
  python -m reporte.main --sheets                                             # cuenta desde Gmail, tarjeta desde entrada/
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .config import Config
from .pipeline import latest_file, procesar
from . import report_pdf


def run(cuenta_pdf, tarjeta_xls, cfg: Config, send: bool, use_llm: bool, preguntar: bool = False, sheets: bool = False) -> Path:
    r = procesar(cuenta_pdf, tarjeta_xls, cfg, use_llm=use_llm, preguntar=preguntar, sheets=sheets)
    agg = r.agg
    print(f"Reporte: {r.pdf}\nDatos guardados en {cfg.data_dir / r.periodo}")
    if sheets:
        from . import categorizer, sheets_client

        print("Google Sheets:", sheets_client.save_month(cfg, r.periodo, r.movs, agg))
        sheets_client.push_comercios(cfg, categorizer.comercios_resumen(r.movs, cfg, r.pendientes), categorizer.CATEGORIAS)
    print(f"Ingresos {agg['ingresos']:,.0f} | Gastos {agg['gastos']:,.0f} (cuenta {agg['gastos_cuenta_corriente']:,.0f} + tarjeta {agg['gastos_tarjeta']:,.0f})")
    for k, v in agg["conciliacion"].items():
        print(f"Conciliacion {k}: {'OK' if not v else f'DIFERENCIA {v:,.0f} -> revisar extraccion'}")
    if r.pendientes:
        donde = "la pestana 'Clasificar' de Google Sheets (columna corregir_a)" if sheets else "python -m reporte.clasificar (o la interfaz grafica)"
        print(f"{len(r.pendientes)} clasificaciones con duda (total ${sum(p['total'] for p in r.pendientes):,.0f}). Respondelas en {donde} y vuelve a correr el reporte.")
    print(r.log.summary(cfg))
    if send:
        from . import gmail_client

        gmail_client.send_report(cfg, f"Reporte financiero - {r.periodo}", report_pdf.build_email_html(r.meta, agg, r.insights), r.pdf)
        print("Correo enviado.")
    return r.pdf


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
