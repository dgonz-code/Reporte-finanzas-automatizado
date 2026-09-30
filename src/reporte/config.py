import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    model: str = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
    gmail_query: str = os.getenv("GMAIL_QUERY", "has:attachment filename:pdf newer_than:35d")
    pdf_password: str | None = os.getenv("PDF_PASSWORD") or None
    report_to: str | None = os.getenv("REPORT_TO") or None
    credentials_file: Path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
    token_file: Path = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "output"))
