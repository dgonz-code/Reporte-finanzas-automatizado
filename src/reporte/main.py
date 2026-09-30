"""Flujo completo: Gmail -> PDF -> Claude -> reporte PDF -> correo.

Uso:
  python -m reporte.main                 # descarga de Gmail y envia el reporte
  python -m reporte.main --pdf cartola.pdf --no-send   # prueba local sin Gmail
"""
import argparse
import json
from pathlib import Path

import anthropic

from . import analyzer, gmail_client, pdf_parser, report_pdf
from .config import Config


def run(pdfs: list[Path], cfg: Config, send: bool) -> Path:
    text = "\n\n".join(pdf_parser.extract_text(p, cfg.pdf_password) for p in pdfs)
    client = anthropic.Anthropic()
    data = analyzer.extract_statement(client, cfg, text)
    agg = analyzer.aggregate(data)
    insights = analyzer.generate_insights(client, cfg, data, agg)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    slug = data["periodo"].lower().replace(" ", "-")
    out = cfg.output_dir / f"reporte-{slug}.pdf"
    report_pdf.build_pdf(out, data, agg, insights)
    (cfg.output_dir / f"movimientos-{slug}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    print(f"Reporte generado: {out}")

    if agg["diferencia_conciliacion"]:
        print(f"AVISO: los saldos no cuadran (diferencia {agg['diferencia_conciliacion']}). Revisa los movimientos extraidos.")
    if send:
        gmail_client.send_report(cfg, f"Reporte financiero - {data['periodo']}", report_pdf.build_email_html(data, agg, insights), out)
        print("Correo enviado.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, nargs="*", help="Usar PDF locales en vez de Gmail")
    ap.add_argument("--no-send", action="store_true", help="No enviar el correo")
    args = ap.parse_args()
    cfg = Config()
    pdfs = args.pdf or gmail_client.download_statements(cfg, cfg.output_dir / "inbox")
    run(pdfs, cfg, send=not args.no_send)


if __name__ == "__main__":
    main()
