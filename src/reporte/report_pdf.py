"""Genera el PDF de analisis detallado y el resumen HTML para el correo."""
import html
from io import BytesIO
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def clp(x: float, moneda: str = "CLP") -> str:
    s = f"{abs(x):,.0f}".replace(",", ".")
    return f"{'-' if x < 0 else ''}${s}" if moneda == "CLP" else f"{x:,.2f} {moneda}"


def _category_chart(by_cat: dict[str, float]) -> BytesIO:
    items = list(by_cat.items())[:10][::-1]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    ax.barh([k for k, _ in items], [v for _, v in items], color="#2F5D8C")
    ax.set_title("Gastos por categoria")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v/1000:,.0f}k")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def build_pdf(path: Path, data: dict, agg: dict, insights: dict) -> None:
    m = data["moneda"]
    ss = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    e = [
        Paragraph(f"Reporte financiero - {html.escape(data['periodo'])}", ss["Title"]),
        Paragraph(html.escape(data["banco"]), ss["Normal"]),
        Spacer(1, 12),
        Paragraph("Resumen ejecutivo", ss["Heading2"]),
        Paragraph(html.escape(insights["resumen_ejecutivo"]), ss["BodyText"]),
        Spacer(1, 8),
    ]

    kpis = [
        ["Ingresos", clp(agg["ingresos"], m)],
        ["Gastos", clp(agg["gastos"], m)],
        ["Balance del mes", clp(agg["balance"], m)],
        ["Tasa de ahorro", f"{agg['tasa_ahorro']:.0%}" if agg["tasa_ahorro"] is not None else "n/d"],
        ["Movimientos", str(agg["n_movimientos"])],
    ]
    t = Table(kpis, colWidths=[6 * cm, 5 * cm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke), ("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    e += [t, Spacer(1, 12)]

    for title, key in (("Hallazgos", "hallazgos"), ("Alertas", "alertas"), ("Recomendaciones", "recomendaciones")):
        if insights[key]:
            e.append(Paragraph(title, ss["Heading2"]))
            e += [Paragraph(f"&bull; {html.escape(x)}", ss["BodyText"]) for x in insights[key]]

    e += [PageBreak(), Paragraph("Gastos por categoria", ss["Heading2"])]
    if agg["gastos_por_categoria"]:
        e.append(Image(_category_chart(agg["gastos_por_categoria"]), width=16 * cm, height=8.2 * cm))
        rows = [["Categoria", "Monto", "% del gasto"]] + [
            [k, clp(v, m), f"{v / agg['gastos']:.0%}"] for k, v in agg["gastos_por_categoria"].items()
        ]
        tt = Table(rows, colWidths=[8 * cm, 4 * cm, 3 * cm], repeatRows=1)
        tt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        e += [Spacer(1, 8), tt]

    e += [Spacer(1, 14), Paragraph("Diez mayores gastos", ss["Heading2"])]
    rows = [["Fecha", "Descripcion", "Monto"]] + [
        [g["fecha"], Paragraph(html.escape(g["descripcion"]), ss["BodyText"]), clp(g["monto"], m)] for g in agg["mayores_gastos"]
    ]
    tg = Table(rows, colWidths=[2.5 * cm, 10 * cm, 4.5 * cm], repeatRows=1)
    tg.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("ALIGN", (2, 0), (2, -1), "RIGHT")]))
    e.append(tg)

    if agg["comercios_recurrentes"]:
        e += [Spacer(1, 14), Paragraph("Cargos repetidos (posibles suscripciones)", ss["Heading2"])]
        rows = [["Descripcion", "Veces", "Total"]] + [
            [Paragraph(html.escape(d), ss["BodyText"]), str(v["veces"]), clp(v["total"], m)]
            for d, v in sorted(agg["comercios_recurrentes"].items(), key=lambda kv: -kv[1]["total"])[:15]
        ]
        tr = Table(rows, colWidths=[10 * cm, 2 * cm, 5 * cm], repeatRows=1)
        tr.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("ALIGN", (1, 0), (-1, -1), "RIGHT")]))
        e.append(tr)

    doc.build(e)


def build_email_html(data: dict, agg: dict, insights: dict) -> str:
    m = data["moneda"]
    li = lambda xs: "".join(f"<li>{html.escape(x)}</li>" for x in xs)
    cats = "".join(
        f"<tr><td>{html.escape(k)}</td><td align='right'>{clp(v, m)}</td></tr>"
        for k, v in list(agg["gastos_por_categoria"].items())[:5]
    )
    return f"""<h2>Reporte financiero - {html.escape(data['periodo'])}</h2>
<p>{html.escape(insights['resumen_ejecutivo'])}</p>
<p><b>Ingresos:</b> {clp(agg['ingresos'], m)} &nbsp; <b>Gastos:</b> {clp(agg['gastos'], m)} &nbsp; <b>Balance:</b> {clp(agg['balance'], m)}</p>
<h3>Principales hallazgos</h3><ul>{li(insights['hallazgos'])}</ul>
{'<h3>Alertas</h3><ul>' + li(insights['alertas']) + '</ul>' if insights['alertas'] else ''}
<h3>Top 5 categorias de gasto</h3><table cellpadding='4'>{cats}</table>
<p>El analisis detallado va en el PDF adjunto.</p>"""
