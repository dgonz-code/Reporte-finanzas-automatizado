"""Busca el correo de la cartola, descarga los PDF adjuntos y envia el reporte."""
import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from googleapiclient.discovery import build

from . import google_auth
from .config import Config


def _service(cfg: Config):
    return build("gmail", "v1", credentials=google_auth.credentials(cfg))


def download_statement(cfg: Config, dest: Path, query: str, exts: tuple[str, ...]) -> Path:
    """Descarga el primer adjunto con alguna de las extensiones, del correo mas reciente que calce con query."""
    svc = _service(cfg)
    res = svc.users().messages().list(userId="me", q=query, maxResults=5).execute()
    msgs = res.get("messages", [])
    if not msgs:
        raise SystemExit(f"No se encontraron correos con la busqueda: {query}")

    dest.mkdir(parents=True, exist_ok=True)
    msg = svc.users().messages().get(userId="me", id=msgs[0]["id"]).execute()
    saved: list[Path] = []

    def walk(part):
        yield part
        for sub in part.get("parts", []):
            yield from walk(sub)

    for part in walk(msg["payload"]):
        name = part.get("filename", "")
        if not name.lower().endswith(exts):
            continue
        body = part["body"]
        if "attachmentId" in body:
            data = svc.users().messages().attachments().get(
                userId="me", messageId=msg["id"], id=body["attachmentId"]
            ).execute()["data"]
        else:
            data = body["data"]
        path = dest / name
        path.write_bytes(base64.urlsafe_b64decode(data))
        saved.append(path)
    if not saved:
        raise SystemExit(f"El correo encontrado no tiene adjuntos {exts}.")
    return saved[0]


def send_report(cfg: Config, subject: str, body_html: str, attachment: Path) -> None:
    svc = _service(cfg)
    to = cfg.report_to or svc.users().getProfile(userId="me").execute()["emailAddress"]
    em = EmailMessage()
    em["To"] = to
    em["Subject"] = subject
    em.set_content("Tu cliente de correo no soporta HTML. Revisa el PDF adjunto.")
    em.add_alternative(body_html, subtype="html")
    ctype = mimetypes.guess_type(attachment.name)[0] or "application/pdf"
    maintype, subtype = ctype.split("/")
    em.add_attachment(attachment.read_bytes(), maintype=maintype, subtype=subtype, filename=attachment.name)
    raw = base64.urlsafe_b64encode(em.as_bytes()).decode()
    svc.users().messages().send(userId="me", body={"raw": raw}).execute()
