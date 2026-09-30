"""Extrae el texto de una cartola PDF (con soporte para PDF protegidos con clave)."""
from pathlib import Path

import pdfplumber


def extract_text(path: Path, password: str | None = None) -> str:
    pages = []
    with pdfplumber.open(path, password=password) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            pages.append(f"--- Pagina {i} ---\n{page.extract_text(layout=True) or ''}")
    text = "\n".join(pages)
    if len(text.strip()) < 50:
        raise ValueError(f"{path.name}: no se pudo extraer texto (¿PDF escaneado?).")
    return text
