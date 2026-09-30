"""Flujo: cuenta corriente (PDF) + tarjeta (XLS) -> categorias -> reporte PDF -> correo.

Uso:
  python -m reporte.main --cuenta entrada/cartola.pdf --tarjeta entrada/tarjeta.xls --no-send
  python -m reporte.main --tarjeta entrada/tarjeta.xls --sin-llm --no-send    # $0, solo reglas
  python -m reporte.main                                                      # desde Gmail y envia
"""
import argparse
from pathlib import Path

import anthropic

from . import analyzer, categorizer, report_pdf, store
from .card_parser import parse_card_statement
from .config import Config
from .llm import UsageLog


def run(cuenta_pdf: Path | None, tarjeta_xls: Path | None, cfg: Config, send: bool, use_llm: bool) -> Path:
    if not (cuenta_pdf or tarjeta_xls):
        raise SystemExit("Indica al menos --cuenta o --tarjeta.")
    log = UsageLog()
    client = anthropic.Anthropic() if use_llm else None

    movs, cuenta, tarjeta = [], None, None
    if tarjeta_xls:
        tarjeta = parse_card_statement(tarjeta_xls)  # sin LLM
        movs += [{**m, "fuente": "tarjeta_credito"} for m in tarjeta["movimientos"]]
    if cuenta_pdf:
        if not use_llm:
            raise SystemExit("La cuenta corriente (PDF) requiere LLM; quita --sin-llm o usa solo --tarjeta.")
        from . import pdf_parser  # import perezoso: solo se necesita con cuenta corriente

        cuenta = analyzer.extract_account(client, cfg, log, pdf_parser.extract_text(cuenta_pdf, cfg.pdf_password))
        movs += [{**m, "fuente": "cuenta_corriente"} for m in cuenta["movimientos"]]

    sin_cat = categorizer.categorize(movs, cfg, client, log, use_llm)
    agg = analyzer.aggregate(movs, cuenta, tarjeta)

    # Periodo = mes del estado de cuenta de la tarjeta (o de la cuenta corriente)
    if tarjeta and tarjeta["fecha_estado"]:
        periodo_iso = tarjeta["fecha_estado"][:7]
    else:
        periodo_iso = max(m["fecha"] for m in movs)[:7]
    meta = {"periodo": periodo_iso, "moneda": "CLP",
            "banco": " + ".join(filter(None, [cuenta and cuenta["banco"], tarjeta and f"Tarjeta {tarjeta['tarjeta']}"]))}
    insights = analyzer.generate_insights(client, cfg, log, meta, agg) if use_llm else analyzer.basic_insights(agg)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.output_dir / f"reporte-{periodo_iso}.pdf"
    report_pdf.build_pdf(out, meta, agg, insights)
    store.save_month(cfg.data_dir, periodo_iso, movs, agg)

    print(f"Reporte: {out}\nDatos guardados en {cfg.data_dir / periodo_iso}")
    print(f"Ingresos {agg['ingresos']:,.0f} | Gastos {agg['gastos']:,.0f} (cuenta {agg['gastos_cuenta_corriente']:,.0f} + tarjeta {agg['gastos_tarjeta']:,.0f})")
    for k, v in agg["conciliacion"].items():
        print(f"Conciliacion {k}: {'OK' if not v else f'DIFERENCIA {v:,.0f} -> revisar extraccion'}")
    if sin_cat:
        print(f"{len(sin_cat)} comercios sin categoria (agregalos a reglas_categorias.json): {sin_cat[:10]}")
    print(log.summary(cfg))

    if send:
        from . import gmail_client

        gmail_client.send_report(cfg, f"Reporte financiero - {periodo_iso}", report_pdf.build_email_html(meta, agg, insights), out)
        print("Correo enviado.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuenta", type=Path, help="PDF de cuenta corriente (local)")
    ap.add_argument("--tarjeta", type=Path, help="XLS de tarjeta de credito (local)")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--sin-llm", action="store_true", help="Solo reglas y parser, costo $0")
    args = ap.parse_args()
    cfg = Config()
    cuenta, tarjeta = args.cuenta, args.tarjeta
    if not (cuenta or tarjeta):  # modo Gmail
        from . import gmail_client

        cuenta = gmail_client.download_statement(cfg, cfg.output_dir / "inbox", cfg.gmail_query_cuenta, (".pdf",))
        tarjeta = gmail_client.download_statement(cfg, cfg.output_dir / "inbox", cfg.gmail_query_tarjeta, (".xls", ".xlsx"))
    run(cuenta, tarjeta, cfg, send=not args.no_send, use_llm=not args.sin_llm)


if __name__ == "__main__":
    main()
