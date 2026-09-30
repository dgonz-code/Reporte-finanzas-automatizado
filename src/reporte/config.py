import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    # Sonnet 5.5 con esfuerzo bajo: la tarea es extraer/clasificar, no razonar en profundidad.
    model: str = os.getenv("REPORTE_MODEL", "claude-sonnet-5-5")
    effort: str = os.getenv("REPORTE_EFFORT", "low")
    # USD por millon de tokens (Sonnet 5.5); solo para estimar el costo de cada ejecucion.
    price_in: float = float(os.getenv("PRICE_IN_PER_MTOK", "2.0"))
    price_out: float = float(os.getenv("PRICE_OUT_PER_MTOK", "10.0"))

    use_web: bool = os.getenv("REPORTE_WEB", "1") == "1"  # busqueda web para comercios dudosos
    ask_min_amount: float = float(os.getenv("REPORTE_ASK_MIN", "20000"))  # no te preguntes por montos menores

    gmail_query_cuenta: str = os.getenv("GMAIL_QUERY_CUENTA", "has:attachment filename:pdf newer_than:35d")
    gmail_query_tarjeta: str = os.getenv("GMAIL_QUERY_TARJETA", "has:attachment filename:xls newer_than:35d")
    pdf_password: str | None = os.getenv("PDF_PASSWORD") or None
    report_to: str | None = os.getenv("REPORT_TO") or None

    credentials_file: Path = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json"))
    token_file: Path = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    output_dir: Path = Path(os.getenv("OUTPUT_DIR", "output"))
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))  # historial para tendencias (gitignored)
