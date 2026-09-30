"""Piezas visuales de la interfaz: estilos, tarjetas y grafico de barras en HTML (sin dependencias)."""
from __future__ import annotations

import html

CSS = """
<style>
.block-container{max-width:1120px;padding-top:2.2rem}
h1,h2,h3{letter-spacing:-.01em}
[data-testid="stMetric"]{border:1px solid rgba(128,128,128,.25);border-radius:16px;padding:16px 18px;
  background:rgba(128,128,128,.06)}
[data-testid="stMetricLabel"] p{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;opacity:.7}
[data-testid="stMetric"]{min-height:122px}
[data-testid="stMetricValue"]{font-weight:650;font-variant-numeric:tabular-nums;font-size:clamp(1.3rem,2.3vw,1.85rem)}
[data-testid="stMetricValue"] *{overflow:visible!important;text-overflow:clip!important;white-space:nowrap}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:16px}
.stButton>button,.stDownloadButton>button{border-radius:10px;font-weight:550}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:.35rem .5rem;border-radius:10px}
[data-baseweb="tab-highlight"]{background-color:#2a78d6!important}
.stTabs [aria-selected="true"]{color:#2a78d6!important}
button[kind="primary"]{background-color:#2a78d6!important;border-color:#2a78d6!important;color:#fff!important}
.hero{display:flex;align-items:baseline;gap:.8rem;margin:0 0 .4rem}
.hero h1{margin:0;font-size:2rem}
.chip{display:inline-flex;align-items:center;gap:.4rem;padding:.25rem .7rem;border-radius:999px;font-size:.82rem;
  border:1px solid rgba(128,128,128,.3);margin:0 .4rem .4rem 0}
.chip.ok{color:#0f8a5f;border-color:rgba(15,138,95,.45);background:rgba(15,138,95,.10)}
.chip.bad{color:#d13b3b;border-color:rgba(209,59,59,.5);background:rgba(209,59,59,.10)}
.chip.warn{color:#b87500;border-color:rgba(184,117,0,.5);background:rgba(184,117,0,.10)}
.lead{font-size:1.08rem;line-height:1.5;margin:.2rem 0 1rem}
.viz{--bar:#2a78d6;--track:rgba(128,128,128,.16);--muted:rgba(128,128,128,.95);width:100%}
@media (prefers-color-scheme: dark){.viz{--bar:#3987e5}}
.viz .row{display:grid;grid-template-columns:minmax(120px,240px) 1fr 150px;align-items:center;gap:12px;padding:5px 0}
.viz .lab{font-size:.92rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.viz .track{height:12px;background:var(--track);border-radius:0 6px 6px 0}
.viz .bar{height:12px;background:var(--bar);border-radius:0 6px 6px 0}
.viz .val{font-size:.9rem;font-variant-numeric:tabular-nums;text-align:right}
.viz .pct{color:var(--muted);margin-left:.5rem;font-size:.8rem}
.viz .row:hover .lab,.viz .row:hover .val{font-weight:650}
</style>
"""


def chip(texto: str, tipo: str = "ok") -> str:
    icono = {"ok": "✓", "bad": "✕", "warn": "!"}[tipo]  # icono + texto: el estado nunca depende solo del color
    return f'<span class="chip {tipo}">{icono} {html.escape(texto)}</span>'


def barras(datos: dict[str, float], fmt, max_items: int = 10) -> str:
    """Barras horizontales de una sola serie: finas, valor en la punta, sin leyenda."""
    items = [(k, v) for k, v in datos.items() if v > 0]
    if len(items) > max_items:
        resto = sum(v for _, v in items[max_items - 1:])
        items = items[:max_items - 1] + [(f"Otras ({len(items) - max_items + 1})", resto)]
    total = sum(v for _, v in items) or 1
    tope = max(v for _, v in items) if items else 1
    filas = "".join(
        f'<div class="row" title="{html.escape(k)}: {fmt(v)} ({v / total:.0%})">'
        f'<div class="lab">{html.escape(k)}</div>'
        f'<div class="track"><div class="bar" style="width:{v / tope * 100:.1f}%"></div></div>'
        f'<div class="val">{fmt(v)}<span class="pct">{v / total:.0%}</span></div></div>'
        for k, v in items
    )
    return f'<div class="viz" role="img" aria-label="Gastos por categoria">{filas}</div>'
