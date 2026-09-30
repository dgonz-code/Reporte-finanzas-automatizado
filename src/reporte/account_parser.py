"""Parser determinista de la cartola de cuenta corriente Scotiabank (PDF).

El PDF trae una sola columna de monto + saldo corrido, asi que el signo se obtiene
de la variacion del saldo (sube = abono, baja = cargo). Se valida contra los totales
que declara el propio documento; si algo no cuadra, main cae al extractor con LLM.
Usa pypdfium2 (soporta PDF con clave, sin dependencias nativas extra).
"""
from __future__ import annotations

import re
from pathlib import Path

import pypdfium2 as pdfium

MESES = {m: i for i, m in enumerate(["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"], 1)}
LINE = re.compile(r"^(\d{2}) / ([A-Z]{3}) (.+?)\s+(\d{8})\s+([\d.]+)\s+(-?[\d.]+)$")
NUM = lambda s: float(s.replace(".", ""))  # noqa: E731


def extract_text(path: Path, password: str | None = None) -> str:
    pdf = pdfium.PdfDocument(str(path), password=password)
    text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
    if len(text.strip()) < 50:
        raise ValueError(f"{path.name}: sin texto extraible (¿PDF escaneado?).")
    return text


def parse_account_text(text: str) -> dict:
    lines = [l.strip() for l in text.splitlines()]
    rango = re.search(r"(\d{2})/([A-Z]{3})/(\d{4})\s+(\d{2})/([A-Z]{3})/(\d{4})", text)
    if not rango:
        raise ValueError("No se encontro el periodo de la cartola.")
    year, mes_hasta = int(rango.group(6)), MESES[rango.group(5)]

    i = next(i for i, l in enumerate(lines) if l.startswith("SALDO ANTERIOR"))
    nums = re.findall(r"-?[\d.]+", lines[i + 1])
    saldo_ant, abonos_decl, cargos_decl, saldo_final = (NUM(n) for n in nums[:4])

    titular = re.search(r"SR\(A\):\s*(.+)", text)
    movs, prev, anomalias = [], saldo_ant, 0
    for l in lines:
        m = LINE.match(l)
        if not m:
            continue
        dd, mon, desc, _docto, monto, saldo = m.groups()
        monto, saldo = NUM(monto), NUM(saldo)
        delta = round(saldo - prev, 2)
        if abs(abs(delta) - monto) > 0.5:
            anomalias += 1
        prev = saldo
        movs.append({"fecha": f"{year}-{MESES[mon]:02d}-{int(dd):02d}", "descripcion": re.sub(r"\s+", " ", desc), "monto": delta})

    abonos = sum(m["monto"] for m in movs if m["monto"] > 0)
    cargos = -sum(m["monto"] for m in movs if m["monto"] < 0)
    return {
        "fuente": "cuenta_corriente", "banco": "Scotiabank", "moneda": "CLP",
        "periodo": f"{year}-{mes_hasta:02d}",
        "titular": titular.group(1).strip() if titular else None,  # solo en memoria: no se guarda en data/
        "saldo_inicial": saldo_ant, "saldo_final": saldo_final,
        "totales_declarados": {"abonos": abonos_decl, "cargos": cargos_decl},
        "movimientos": movs,
        "valido": bool(movs) and anomalias == 0 and abs(abonos - abonos_decl) < 1 and abs(cargos - cargos_decl) < 1 and abs(prev - saldo_final) < 1,
    }


def parse_account_statement(path: Path, password: str | None = None) -> dict:
    return parse_account_text(extract_text(path, password))
