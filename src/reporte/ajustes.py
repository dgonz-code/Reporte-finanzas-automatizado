"""Ajustes no secretos (data/ajustes.json) y presupuesto (data/presupuesto.json) de la interfaz grafica."""
from __future__ import annotations

import dataclasses
import json
import shutil

from . import secrets_store
from .config import Config

DEFAULTS = {"llm": "none", "gmail_email": "", "remitente": "cartolas.info@scotiabank.cl", "dias": 45, "report_to": ""}


def load(cfg: Config) -> dict:
    f = cfg.data_dir / "ajustes.json"
    return {**DEFAULTS, **(json.loads(f.read_text()) if f.exists() else {})}


def save(cfg: Config, ajustes: dict) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "ajustes.json").write_text(json.dumps(ajustes, ensure_ascii=False, indent=1))


def make_config(base: Config | None = None) -> Config:
    """Config efectiva: variables de entorno + ajustes de la interfaz + claves del Llavero."""
    base = base or Config()
    a = load(base)
    return dataclasses.replace(
        base,
        llm=a["llm"] if a["llm"] != "none" or base.llm == "none" else base.llm,
        pdf_password=secrets_store.get("pdf_password") or base.pdf_password,
        report_to=a["report_to"] or base.report_to,
    )


def gmail_query(a: dict) -> str:
    return f"from:{a['remitente']} has:attachment filename:pdf newer_than:{int(a['dias'])}d"


def claude_disponible() -> bool:
    return shutil.which("claude") is not None


def load_presupuesto(cfg: Config) -> dict[str, float]:
    f = cfg.data_dir / "presupuesto.json"
    return json.loads(f.read_text()) if f.exists() else {}


def save_presupuesto(cfg: Config, pres: dict[str, float]) -> None:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "presupuesto.json").write_text(json.dumps({k: v for k, v in pres.items() if v}, ensure_ascii=False, indent=1))
