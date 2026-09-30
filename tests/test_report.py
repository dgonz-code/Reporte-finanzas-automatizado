from reporte.analyzer import aggregate
from reporte.report_pdf import build_email_html, build_pdf

META = {"banco": "Banco Demo", "periodo": "2026-08", "moneda": "CLP"}
MOVS = [
    {"fuente": "cuenta_corriente", "descripcion": "Sueldo", "monto": 2000000, "categoria": "Sueldo e ingresos", "fecha": "2026-08-01"},
    {"fuente": "tarjeta_credito", "descripcion": "Netflix", "monto": -9990, "categoria": "Entretenimiento y suscripciones", "fecha": "2026-08-03"},
    {"fuente": "tarjeta_credito", "descripcion": "Netflix", "monto": -9990, "categoria": "Entretenimiento y suscripciones", "fecha": "2026-08-13"},
    {"fuente": "cuenta_corriente", "descripcion": "Arriendo", "monto": -880020, "categoria": "Vivienda y cuentas basicas", "fecha": "2026-08-20"},
]
INSIGHTS = {"resumen_ejecutivo": "Mes con ahorro.", "hallazgos": ["a"], "alertas": [], "recomendaciones": ["b"]}


def test_aggregate_recurrentes():
    agg = aggregate(MOVS)
    assert agg["ingresos"] == 2000000
    assert agg["gastos"] == 900000
    assert agg["comercios_recurrentes"]["NETFLIX"]["veces"] == 2


def test_pdf_and_email(tmp_path):
    agg = aggregate(MOVS)
    out = tmp_path / "r.pdf"
    build_pdf(out, META, agg, INSIGHTS)
    assert out.read_bytes().startswith(b"%PDF")
    assert "2026-08" in build_email_html(META, agg, INSIGHTS)
