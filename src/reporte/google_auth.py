"""Credenciales OAuth compartidas por Gmail y Google Sheets."""
from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import Config

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]


def credentials(cfg: Config) -> Credentials:
    creds = None
    if cfg.token_file.exists():
        creds = Credentials.from_authorized_user_file(str(cfg.token_file), SCOPES)
    if creds and not creds.has_scopes(SCOPES):  # token antiguo sin permiso de Sheets: reautorizar
        creds = None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(cfg.credentials_file), SCOPES).run_local_server(port=0)
        cfg.token_file.write_text(creds.to_json())
    return creds
