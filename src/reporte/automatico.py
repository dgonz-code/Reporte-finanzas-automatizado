"""Ejecucion desatendida (la lanza macOS con launchd; ver launchd.py).

Baja la cartola de la cuenta corriente desde Gmail, toma el .xls de la tarjeta de la carpeta de entrada,
genera el reporte y te lo envia por correo. Nunca usa IA (no hay nadie para confirmar sugerencias).
Si falta algo, te avisa con una notificacion de macOS y no envia nada a medias.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

from . import account_parser, ajustes, mail_client, pipeline, report_pdf, secrets_store
from .card_parser import parse_card_statement

MAX_EDAD_TARJETA_DIAS = 40


def notificar(titulo: str, texto: str) -> None:
    print(f"[{titulo}] {texto}")
    if sys.platform == "darwin":
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
        subprocess.run(["osascript", "-e", f'display notification "{esc(texto)}" with title "{esc(titulo)}"'], check=False)


def _hash(*paths: Path | None) -> str:
    h = hashlib.sha1()
    for p in paths:
        h.update(p.read_bytes() if p else b"-")
    return h.hexdigest()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="Procesar aunque ya se haya hecho con estos mismos archivos")
    ap.add_argument("--sin-enviar", action="store_true", help="Generar el reporte pero no enviar el correo")
    ap.add_argument("--solo-cuenta", action="store_true", help="Enviar aunque falte la tarjeta")
    args = ap.parse_args(argv)

    cfg = ajustes.make_config()
    a = ajustes.load(cfg)
    clave = secrets_store.get("gmail_app_password")
    if not (a["gmail_email"] and clave):
        notificar("Reporte financiero", "Falta conectar Gmail: abre la aplicacion y completa Ajustes.")
        return 1

    try:
        cuenta = mail_client.download_statement(a["gmail_email"], clave, ajustes.gmail_query(a), cfg.output_dir / "inbox", (".pdf",))
    except FileNotFoundError:
        print("Aun no llega la cartola de este mes; se reintentara en la proxima ejecucion.")
        return 0
    except Exception as e:
        notificar("Reporte financiero: error con Gmail", str(e)[:200])
        return 1

    tarjeta = pipeline.latest_file(cfg.inbox_dir, cfg.inbox_card_glob)
    if tarjeta and time.time() - tarjeta.stat().st_mtime > MAX_EDAD_TARJETA_DIAS * 86400:
        tarjeta = None  # es de un mes anterior
    if not tarjeta and not args.solo_cuenta:
        notificar("Reporte financiero: falta la tarjeta", f"Llego la cartola. Descarga el .xls de la tarjeta y dejalo en {cfg.inbox_dir}/")
        return 0

    estado = cfg.data_dir / "automatico_estado.json"
    huella = _hash(cuenta, tarjeta)
    if not args.forzar and estado.exists() and json.loads(estado.read_text()).get("huella") == huella:
        print("Estos archivos ya se procesaron; nada que hacer.")
        return 0

    try:  # los dos archivos deben ser del mismo mes; si no, algo esta desfasado
        p_cuenta = account_parser.parse_account_statement(cuenta, cfg.pdf_password)["periodo"]
        p_tarjeta = (parse_card_statement(tarjeta)["fecha_estado"] or "")[:7] if tarjeta else p_cuenta
    except Exception as e:
        notificar("Reporte financiero: no pude leer la cartola", f"{e}"[:200] + " Revisa la clave del PDF en Ajustes.")
        return 1
    if p_cuenta != p_tarjeta:
        notificar("Reporte financiero: archivos de meses distintos", f"La cuenta es de {p_cuenta} y la tarjeta de {p_tarjeta}. Revisa y usa la aplicacion.")
        return 1

    try:
        r = pipeline.procesar(cuenta, tarjeta, cfg, use_llm=False)
        if not args.sin_enviar:
            mail_client.send_report(a["gmail_email"], clave, a["report_to"] or None, f"Reporte financiero - {r.periodo}",
                                    report_pdf.build_email_html(r.meta, r.agg, r.insights), r.pdf)
    except Exception as e:
        notificar("Reporte financiero: error", str(e)[:200])
        return 1

    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    estado.write_text(json.dumps({"huella": huella, "periodo": r.periodo}))
    dudas = f" {len(r.pendientes)} clasificaciones por confirmar." if r.pendientes else ""
    notificar(f"Reporte {r.periodo} listo", f"Gastos {report_pdf.clp(r.agg['gastos'])}." + dudas + (" Enviado a tu correo." if not args.sin_enviar else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
