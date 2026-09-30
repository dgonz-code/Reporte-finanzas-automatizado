from reporte.analyzer import aggregate
from reporte.report_pdf import build_email_html, build_pdf

DATA = {
    "banco": "Banco Demo", "periodo": "Agosto 2026", "moneda": "CLP",
    "saldo_inicial": 100000, "saldo_final": 1050000,
    "movimientos": [
        {"fecha": "2026-08-01", "descripcion": "Sueldo", "monto": 2000000, "categoria": "Sueldo e ingresos"},
        {"fecha": "2026-08-03", "descripcion": "Netflix", "monto": -9990, "categoria": "Entretenimiento y suscripciones"},
        {"fecha": "2026-08-13", "descripcion": "Netflix", "monto": -9990, "categoria": "Entretenimiento y suscripciones"},
        {"fecha": "2026-08-05", "descripcion": "Lider", "monto": -150000, "categoria": "Supermercado"},
        {"fecha": "2026-08-20", "descripcion": "Arriendo", "monto": -880020, "categoria": "Vivienda y cuentas basicas"},
    ],
}
INSIGHTS = {"resumen_ejecutivo": "Mes con ahorro.", "hallazgos": ["a"], "alertas": [], "recomendaciones": ["b"]}


def test_aggregate():
    agg = aggregate(DATA)
    assert agg["ingresos"] == 2000000
    assert agg["gastos"] == 1050000
    assert agg["diferencia_conciliacion"] == 0
    assert agg["comercios_recurrentes"]["NETFLIX"]["veces"] == 2


def test_pdf_and_email(tmp_path):
    agg = aggregate(DATA)
    out = tmp_path / "r.pdf"
    build_pdf(out, DATA, agg, INSIGHTS)
    assert out.read_bytes().startswith(b"%PDF")
    assert "Agosto 2026" in build_email_html(DATA, agg, INSIGHTS)
