"""Busca el correo de la cartola, descarga los PDF adjuntos y envia el reporte."""
import base64
import mimetypes
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .config import Config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _service(cfg: Config):
    creds = None
    if cfg.token_file.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(cfg.credentials_file), SCOPES)
            creds = flow.run_local_server(port=0)
        cfg.token_file.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def download_statements(cfg: Config, dest: Path) -> list[Path]:
    """Descarga los PDF del correo mas reciente que calce con GMAIL_QUERY."""
    svc = _service(cfg)
    res = svc.users().messages().list(userId="me", q=cfg.gmail_query, maxResults=5).execute()
    msgs = res.get("messages", [])
    if not msgs:
        raise SystemExit(f"No se encontraron correos con la busqueda: {cfg.gmail_query}")

    dest.mkdir(parents=True, exist_ok=True)
    msg = svc.users().messages().get(userId="me", id=msgs[0]["id"]).execute()
    saved: list[Path] = []

    def walk(part):
        yield part
        for sub in part.get("parts", []):
            yield from walk(sub)

    for part in walk(msg["payload"]):
        name = part.get("filename", "")
        if not name.lower().endswith(".pdf"):
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
        raise SystemExit("El correo encontrado no tiene PDF adjuntos.")
    return saved


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
