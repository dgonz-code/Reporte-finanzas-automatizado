"""Gmail por IMAP/SMTP con una contrasena de aplicacion (sin proyecto de Google Cloud).

Contrasena de aplicacion: cuenta de Google > Seguridad > Verificacion en 2 pasos > Contrasenas de aplicaciones.
"""
from __future__ import annotations

import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from pathlib import Path

IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"


def _name(part) -> str:
    raw = part.get_filename() or ""
    return str(make_header(decode_header(raw))) if raw else ""


def _imap(address: str, app_password: str):
    m = imaplib.IMAP4_SSL(IMAP_HOST)
    m.login(address, app_password.replace(" ", ""))  # Google la muestra con espacios
    return m


def test_connection(address: str, app_password: str) -> str | None:
    """None si conecta; si no, un mensaje de error legible."""
    try:
        m = _imap(address, app_password)
        m.logout()
        return None
    except imaplib.IMAP4.error as e:
        return f"Gmail rechazo las credenciales ({e}). Revisa el correo y la contrasena de aplicacion."
    except OSError as e:
        return f"No hay conexion con Gmail ({e})."


def download_statement(address: str, app_password: str, query: str, dest: Path, exts: tuple[str, ...],
                       max_messages: int = 5) -> Path:
    """Descarga el primer adjunto con alguna de las extensiones, del correo mas reciente que calce con `query`
    (sintaxis de busqueda de Gmail)."""
    m = _imap(address, app_password)
    try:
        m.select("INBOX", readonly=True)
        typ, data = m.search(None, "X-GM-RAW", f'"{query}"')
        ids = data[0].split()[::-1][:max_messages] if typ == "OK" and data and data[0] else []
        if not ids:
            raise FileNotFoundError(f"No se encontraron correos con la busqueda: {query}")
        dest.mkdir(parents=True, exist_ok=True)
        for mid in ids:  # del mas nuevo al mas antiguo
            typ, msgdata = m.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msgdata[0][1])
            for part in msg.walk():
                name = _name(part)
                if name.lower().endswith(exts):
                    path = dest / Path(name).name  # Path.name evita rutas maliciosas
                    path.write_bytes(part.get_payload(decode=True))
                    return path
        raise FileNotFoundError(f"Los correos encontrados no traen adjuntos {exts}.")
    finally:
        try:
            m.logout()
        except Exception:
            pass


def send_report(address: str, app_password: str, to: str | None, subject: str, body_html: str, attachment: Path) -> None:
    em = EmailMessage()
    em["From"], em["To"], em["Subject"] = address, to or address, subject
    em.set_content("Tu cliente de correo no soporta HTML. Revisa el PDF adjunto.")
    em.add_alternative(body_html, subtype="html")
    em.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=attachment.name)
    with smtplib.SMTP_SSL(SMTP_HOST, 465) as s:
        s.login(address, app_password.replace(" ", ""))
        s.send_message(em)
