from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # Motor de IA (opcional). none = $0, sin IA (por defecto). claude-code = usa tu plan de Claude via `claude -p`
    # (sin costo adicional, cuenta contra el cupo del plan). api = API de Anthropic (se paga por uso, aparte del plan).
    llm: str = os.getenv("REPORTE_LLM", "none")
    claude_code_model: str | None = os.getenv("REPORTE_CLAUDE_CODE_MODEL") or None
    # Solo para llm=api: Sonnet 5.5 con esfuerzo bajo.
    model: str = os.getenv("REPORTE_MODEL", "claude-sonnet-5-5")
    effort: str = os.getenv("REPORTE_EFFORT", "low")
    # USD por millon de tokens (Sonnet 5.5); solo para estimar el costo de cada ejecucion.
    price_in: float = float(os.getenv("PRICE_IN_PER_MTOK", "2.0"))
    price_out: float = float(os.getenv("PRICE_OUT_PER_MTOK", "10.0"))

    use_web: bool = os.getenv("REPORTE_WEB", "0") == "1"  # busqueda web para comercios dudosos (solo llm=api)
    ask_min_amount: float = float(os.getenv("REPORTE_ASK_MIN", "20000"))  # no te preguntes por montos menores

    gmail_query_cuenta: str = os.getenv("GMAIL_QUERY_CUENTA", "from:cartolas.info@scotiabank.cl has:attachment filename:pdf newer_than:35d")
    # La tarjeta se descarga a mano: carpeta donde dejas (o donde el navegador guarda) el .xls
    inbox_dir: Path = Path(os.getenv("REPORTE_ENTRADA", "entrada"))
    inbox_card_glob: str = os.getenv("REPORTE_TARJETA_GLOB", "Estado-de-Cuenta*.xls*")
    sheet_id: str | None = os.getenv("REPORTE_SHEET_ID") or None  # Google Sheets destino (opcional)
    pdf_password: str | None = os.getenv("PDF_PASSWORD") or None
    report_to: str | None = os.getenv("REPORT_TO") or None

    credentials_file: Path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
    token_file: Path = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "output"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))  # historial para tendencias (gitignored)
