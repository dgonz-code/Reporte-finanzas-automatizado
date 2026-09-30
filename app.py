"""Interfaz grafica local. Iniciar con iniciar.command (doble clic) o:  streamlit run app.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from reporte import ajustes, categorizer, mail_client, pipeline, report_pdf, secrets_store, ui_kit  # noqa: E402
from reporte.config import Config  # noqa: E402

st.set_page_config(page_title="Finanzas personales", page_icon="💰", layout="wide", initial_sidebar_state="expanded")
st.markdown(ui_kit.CSS, unsafe_allow_html=True)
clp = report_pdf.clp


def html_escape(t: str) -> str:
    import html

    return html.escape(t)


def cfg() -> Config:
    return ajustes.make_config(Config())


def gmail_ok() -> bool:
    a = ajustes.load(cfg())
    return bool(a["gmail_email"] and secrets_store.get("gmail_app_password"))


def use_claude(c: Config) -> bool:
    return c.llm == "claude-code" and ajustes.claude_disponible()


# ------------------------------------------------------------------ Reporte
def pagina_reporte() -> None:
    c = cfg()
    a = ajustes.load(c)
    st.markdown('<div class="hero"><h1>Reporte del mes</h1></div>', unsafe_allow_html=True)
    st.caption("Carga las dos cartolas y genera el reporte. Todo se procesa en este equipo.")
    col1, col2 = st.columns(2)

    with col1, st.container(border=True):
        st.subheader("1 · Cuenta corriente")
        if gmail_ok():
            if st.button("📧 Traer de Gmail", use_container_width=True):
                try:
                    with st.spinner("Buscando el correo del banco…"):
                        p = mail_client.download_statement(a["gmail_email"], secrets_store.get("gmail_app_password"),
                                                           ajustes.gmail_query(a), c.output_dir / "inbox", (".pdf",))
                    st.session_state["cuenta"] = p
                except Exception as e:
                    st.error(str(e))
        else:
            st.info("Conecta Gmail en **Ajustes** para traerla automáticamente.")
        up = st.file_uploader("…o sube el PDF", type="pdf", key="up_cuenta")
        if up:
            c.inbox_dir.mkdir(parents=True, exist_ok=True)
            p = c.inbox_dir / up.name
            p.write_bytes(up.getvalue())
            st.session_state["cuenta"] = p
        if st.session_state.get("cuenta"):
            st.success(f"Lista: {Path(st.session_state['cuenta']).name}")

    with col2, st.container(border=True):
        st.subheader("2 · Tarjeta de crédito")
        up = st.file_uploader("Sube el estado de cuenta descargado del banco", type=["xls", "xlsx"], key="up_tarjeta")
        if up:
            c.inbox_dir.mkdir(parents=True, exist_ok=True)
            p = c.inbox_dir / up.name
            p.write_bytes(up.getvalue())
            st.session_state["tarjeta"] = p
        else:
            ult = pipeline.latest_file(c.inbox_dir, c.inbox_card_glob)
            if ult and st.button(f"Usar el más reciente de la carpeta: {ult.name}", use_container_width=True):
                st.session_state["tarjeta"] = ult
        if st.session_state.get("tarjeta"):
            st.success(f"Lista: {Path(st.session_state['tarjeta']).name}")

    ia = False
    if use_claude(c):
        ia = st.checkbox("Usar Claude (mi plan) para sugerir categorías dudosas y redactar el resumen", value=False)
    elif c.llm == "claude-code":
        st.warning("Activaste Claude en Ajustes, pero no se encontró el comando `claude` en este equipo.")

    listo = st.session_state.get("cuenta") or st.session_state.get("tarjeta")
    if st.button("▶️ Generar reporte", type="primary", disabled=not listo):
        try:
            with st.spinner("Procesando…"):
                msgs: list[str] = []
                st.session_state["res"] = pipeline.procesar(st.session_state.get("cuenta"), st.session_state.get("tarjeta"),
                                                            c, use_llm=ia, say=msgs.append)
                st.session_state["msgs"] = msgs
        except Exception as e:
            st.error(f"No se pudo generar el reporte: {e}")

    meses = pipeline.meses_guardados(c)
    if meses and not st.session_state.get("res"):
        m = st.selectbox("…o abrir un mes ya cargado", meses[::-1])
        if st.button("Abrir"):
            st.session_state["res"] = pipeline.recalcular_mes(c, m)
    if st.session_state.get("res"):
        mostrar_resultado(st.session_state["res"], c, a)


def _mes_anterior(c: Config, periodo: str):
    prev = [m for m in pipeline.meses_guardados(c) if m < periodo]
    return (prev[-1], json.loads((c.data_dir / prev[-1] / "resumen.json").read_text())) if prev else (None, None)


def mostrar_resultado(r, c: Config, a: dict) -> None:
    agg = r.agg
    st.divider()
    st.markdown(f'<div class="hero"><h1>{r.periodo}</h1><span class="chip">{html_escape(r.meta["banco"])}</span></div>', unsafe_allow_html=True)
    for m in st.session_state.get("msgs", []):
        st.warning(m)

    chips = "".join(
        ui_kit.chip(f"{f.replace('_', ' ').capitalize()}: " + ("cuadra con el banco" if not d else f"diferencia de {clp(d)}"), "ok" if not d else "bad")
        for f, d in agg["conciliacion"].items())
    if agg["pendientes"]:
        chips += ui_kit.chip(f"{len(agg['pendientes'])} clasificaciones por confirmar ({clp(sum(p['total'] for p in agg['pendientes']))})", "warn")
    st.markdown(chips, unsafe_allow_html=True)
    st.markdown(f'<p class="lead">{html_escape(r.insights["resumen_ejecutivo"])}</p>', unsafe_allow_html=True)

    mes_prev, prev = _mes_anterior(c, r.periodo)
    k = st.columns(4)
    k[0].metric("Ingresos", clp(agg["ingresos"]), delta=f"{clp(agg['ingresos'] - prev['ingresos'])} vs {mes_prev}" if prev else None)
    k[1].metric("Gastos", clp(agg["gastos"]), delta=f"{clp(agg['gastos'] - prev['gastos'])} vs {mes_prev}" if prev else None,
                delta_color="inverse", help=f"Cuenta corriente {clp(agg['gastos_cuenta_corriente'])} + tarjeta {clp(agg['gastos_tarjeta'])}")
    k[2].metric("Balance", clp(agg["balance"]))
    k[3].metric("Tasa de ahorro", report_pdf.pct(agg["tasa_ahorro"]))

    t1, t2, t3 = st.tabs(["Hallazgos", "Gastos por categoría", "Mayores gastos"])
    with t1:
        cA, cB = st.columns(2)
        with cA, st.container(border=True):
            st.markdown("**Lo más relevante**")
            for h in r.insights["hallazgos"] + ["💡 " + x for x in r.insights["recomendaciones"]]:
                st.markdown(f"- {h}")
        with cB, st.container(border=True):
            st.markdown("**Atención**")
            for x in r.insights["alertas"] or ["Nada que destacar este mes."]:
                st.markdown(f"- {x}")
    with t2:
        st.markdown(ui_kit.barras(agg["gastos_por_categoria"], clp), unsafe_allow_html=True)
        with st.expander("Ver como tabla"):
            st.dataframe(pd.DataFrame({"Categoría": list(agg["gastos_por_categoria"]), "Gasto": list(agg["gastos_por_categoria"].values())}),
                         hide_index=True, use_container_width=True, column_config={"Gasto": st.column_config.NumberColumn(format="localized")})
    with t3:
        st.dataframe(pd.DataFrame([{"Fecha": g["fecha"], "Descripción": g["descripcion"], "Monto": -g["monto"], "Categoría": g["categoria"]}
                                   for g in agg["mayores_gastos"]]), hide_index=True, use_container_width=True,
                     column_config={"Monto": st.column_config.NumberColumn(format="localized")})
    if r.log.calls:
        st.caption(r.log.summary(c))

    b1, b2, _ = st.columns([1, 1, 2])
    b1.download_button("⬇️ Descargar PDF", r.pdf.read_bytes(), file_name=r.pdf.name, mime="application/pdf", use_container_width=True)
    if gmail_ok() and b2.button("✉️ Enviármelo por correo", use_container_width=True):
        try:
            mail_client.send_report(a["gmail_email"], secrets_store.get("gmail_app_password"), a["report_to"] or None,
                                    f"Reporte financiero - {r.periodo}", report_pdf.build_email_html(r.meta, agg, r.insights), r.pdf)
            st.success("Correo enviado.")
        except Exception as e:
            st.error(f"No se pudo enviar: {e}")


# ------------------------------------------------------------------ Clasificar
def pagina_clasificar() -> None:
    c = cfg()
    st.header("Clasificar gastos")
    meses = pipeline.meses_guardados(c)
    if not meses:
        st.info("Primero genera un reporte en la pantalla **Reporte**.")
        return
    st.caption("Lo que tú eliges **manda** sobre las reglas y la IA, y queda guardado: ese comercio no se vuelve a preguntar.")
    periodo = st.selectbox("Mes", meses[::-1])
    filas = pipeline.cargar_comercios(c, periodo)
    solo = st.toggle("Mostrar solo los que necesitan confirmación", value=True)
    df = pd.DataFrame(filas)
    if solo:
        df = df[df["estado"] == "POR CONFIRMAR"]
    if df.empty:
        st.success("No hay nada por confirmar en este mes. 🎉")
    df = df.assign(corregir_a=None)
    editado = st.data_editor(
        df, hide_index=True, use_container_width=True, key=f"ed_{periodo}_{solo}",
        column_order=["estado", "comercio", "monto", "categoria", "fuente", "corregir_a"],
        disabled=["estado", "comercio", "monto", "categoria", "fuente"],
        column_config={
            "monto": st.column_config.NumberColumn("Monto del mes", format="localized"),
            "categoria": "Categoría actual", "fuente": "Decidió",
            "corregir_a": st.column_config.SelectboxColumn("Elegir categoría ▾", options=categorizer.CATEGORIAS, required=False),
        },
    )
    cA, cB = st.columns(2)
    if cA.button("💾 Guardar mis elecciones y actualizar el reporte", type="primary"):
        n = categorizer.aplicar_correcciones(c, editado.dropna(subset=["corregir_a"]).to_dict("records"))
        if n:
            st.session_state["res"] = pipeline.recalcular_mes(c, periodo)
            st.session_state.pop("msgs", None)
            st.success(f"{n} clasificación(es) guardadas. El reporte de {periodo} se actualizó (pantalla Reporte).")
            st.rerun()
        else:
            st.info("No elegiste ninguna categoría.")
    if use_claude(c):
        if cB.button("🤖 Pedir sugerencias a Claude (uso mi plan)"):
            with st.spinner("Claude está revisando los comercios…"):
                r = pipeline.recalcular_mes(c, periodo, use_llm=True)
            st.session_state["res"] = r
            st.success("Listo. Sus sugerencias aparecen como 'IA': confírmalas o corrígelas.")
            st.caption(r.log.summary(c))
            st.rerun()
    else:
        cB.caption("Para usar Claude activa el modo en **Ajustes** (requiere Claude Code instalado).")


# ------------------------------------------------------------------ Historial
def pagina_historial() -> None:
    c = cfg()
    st.header("Historial y presupuesto")
    meses = pipeline.meses_guardados(c)
    if not meses:
        st.info("Aún no hay meses guardados.")
        return
    res = {m: json.loads((c.data_dir / m / "resumen.json").read_text()) for m in meses}
    df = pd.DataFrame({"Ingresos": {m: r["ingresos"] for m, r in res.items()}, "Gastos": {m: r["gastos"] for m, r in res.items()}})
    if len(meses) < 2:
        st.bar_chart(df)
        st.caption("Con un solo mes aún no hay tendencia; se irá completando con cada mes que cargues.")
    else:
        st.line_chart(df)

    st.subheader("Presupuesto mensual")
    pres = ajustes.load_presupuesto(c)
    cats = [x for x in categorizer.CATEGORIAS if x not in categorizer.INTERNOS | categorizer.INGRESOS]
    ed = st.data_editor(pd.DataFrame({"Categoría": cats, "Presupuesto": [float(pres.get(x, 0)) for x in cats]}),
                        hide_index=True, use_container_width=True, disabled=["Categoría"], key="pres",
                        column_config={"Presupuesto": st.column_config.NumberColumn(format="localized", min_value=0)})
    if st.button("Guardar presupuesto"):
        ajustes.save_presupuesto(c, dict(zip(ed["Categoría"], ed["Presupuesto"])))
        st.success("Presupuesto guardado.")
        pres = ajustes.load_presupuesto(c)
    mes = st.selectbox("Comparar mes", meses[::-1])
    gasto = res[mes]["gastos_por_categoria"]
    filas = [{"Categoría": k, "Gasto": gasto.get(k, 0), "Presupuesto": pres.get(k, 0),
              "Diferencia": pres.get(k, 0) - gasto.get(k, 0),
              "Estado": "Sin presupuesto" if not pres.get(k) else ("🔴 Sobre presupuesto" if gasto.get(k, 0) > pres[k] else "🟢 Dentro")}
             for k in sorted(set(gasto) | set(pres), key=lambda k: -gasto.get(k, 0))]
    st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True,
                 column_config={x: st.column_config.NumberColumn(format="localized") for x in ("Gasto", "Presupuesto", "Diferencia")})


# ------------------------------------------------------------------ Ajustes
def pagina_ajustes() -> None:
    c = cfg()
    a = ajustes.load(c)
    st.header("Ajustes")

    st.subheader("📧 Gmail")
    st.markdown("Usa una **contraseña de aplicación** (no tu clave normal): Cuenta de Google → Seguridad → *Verificación en 2 pasos* → "
                "*Contraseñas de aplicaciones*. Se guarda en el Llavero de macOS, no en archivos.")
    a["gmail_email"] = st.text_input("Tu correo de Gmail", a["gmail_email"])
    pw = st.text_input("Contraseña de aplicación (16 letras)", type="password",
                       placeholder="ya guardada ✓" if secrets_store.get("gmail_app_password") else "")
    a["remitente"] = st.text_input("Remitente de las cartolas", a["remitente"])
    a["dias"] = st.number_input("Buscar correos de los últimos (días)", 7, 365, int(a["dias"]))
    a["report_to"] = st.text_input("Enviar el reporte a (vacío = a ti mismo)", a["report_to"])

    st.subheader("🔑 Clave del PDF de la cuenta corriente")
    pdfpw = st.text_input("Clave", type="password", placeholder="ya guardada ✓" if secrets_store.get("pdf_password") else "")

    st.subheader("🤖 Claude (opcional)")
    opciones = {"none": "No usar IA (gratis, recomendado para empezar)", "claude-code": "Usar mi plan de Claude (vía Claude Code)"}
    a["llm"] = st.radio("Modo", list(opciones), format_func=opciones.get, index=list(opciones).index(a["llm"]) if a["llm"] in opciones else 0)
    if a["llm"] == "claude-code":
        if ajustes.claude_disponible():
            st.success("Claude Code encontrado en este equipo.")
        else:
            st.error("No se encontró `claude`. Instálalo desde claude.com/claude-code e inicia sesión; luego vuelve aquí.")

    if st.button("💾 Guardar ajustes", type="primary"):
        for nombre, valor in (("gmail_app_password", pw), ("pdf_password", pdfpw)):
            if valor and not secrets_store.put(nombre, valor):
                st.error("No pude guardar la clave en el Llavero de macOS. Revisa que el Llavero esté desbloqueado.")
        ajustes.save(c, a)
        st.success("Guardado.")
        if a["gmail_email"] and secrets_store.get("gmail_app_password"):
            err = mail_client.test_connection(a["gmail_email"], secrets_store.get("gmail_app_password"))
            (st.error if err else st.success)(err or "✅ Conexión con Gmail correcta.")


# ------------------------------------------------------------------ navegacion
PAGINAS = {"📄 Reporte": pagina_reporte, "🏷️ Clasificar": pagina_clasificar, "📈 Historial": pagina_historial, "⚙️ Ajustes": pagina_ajustes}
with st.sidebar:
    st.title("💰 Finanzas")
    eleccion = st.radio("Ir a", list(PAGINAS), label_visibility="collapsed")
    st.caption(("Gmail conectado ✓" if gmail_ok() else "Gmail sin conectar") + " · IA: " + ("Claude" if cfg().llm == "claude-code" else "apagada"))
PAGINAS[eleccion]()
