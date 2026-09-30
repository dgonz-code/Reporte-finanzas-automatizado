import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from reporte import analyzer, categorizer
from reporte.card_parser import parse_card_statement
from reporte.config import Config
from reporte.llm import UsageLog


class FakeStream:
    def __init__(self, payload):
        self.msg = SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    """Sustituto de anthropic.Anthropic: responde con un payload fijo y registra las llamadas."""

    def __init__(self, payload):
        self.payload, self.calls = payload, []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kw):
        self.calls.append(kw)
        return FakeStream(self.payload)


def cfg(tmp_path):
    return Config(llm="api", data_dir=tmp_path / "data", output_dir=tmp_path / "out")


class FakeWebClient(FakeClient):
    """Ademas responde a messages.create (herramienta de busqueda web)."""

    def __init__(self, payload, web_payload):
        super().__init__(payload)
        self.web_calls = []
        self.messages = SimpleNamespace(stream=self._stream, create=self._create)
        self.web_payload = web_payload

    def _create(self, **kw):
        self.web_calls.append(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=3000, output_tokens=100, cache_read_input_tokens=0),
            content=[SimpleNamespace(type="text", text="Resultado: " + json.dumps(self.web_payload))],
        )


def item(i, cat, conf):
    return {"id": i, "categoria": cat, "confianza": conf, "motivo": "x"}


def test_rules_avoid_llm(tmp_path):
    movs = [{"descripcion": "UNIMARC EL SALVADOR", "monto": -7281}, {"descripcion": "MERPAGO*P 995442205 995442205", "monto": -1590}]
    log = UsageLog()
    assert categorizer.categorize(movs, cfg(tmp_path), FakeClient({}), log) == []
    assert [m["categoria"] for m in movs] == ["Supermercado", "Pagos digitales sin detalle"]
    assert log.calls == []


def test_confident_ai_answer_is_learned_and_never_paid_twice(tmp_path):
    c = cfg(tmp_path)
    fake = FakeClient({"items": [item(0, "Mascotas", 0.95)]})
    movs = [{"descripcion": "VETERINARIA XYZ", "monto": -20000}]
    assert categorizer.categorize(movs, c, fake, UsageLog()) == []
    assert movs[0]["categoria"] == "Mascotas" and len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-sonnet-5-5" and fake.calls[0]["output_config"]["effort"] == "low"
    movs2 = [{"descripcion": "VETERINARIA XYZ", "monto": -5000}]
    categorizer.categorize(movs2, c, fake, UsageLog())
    assert movs2[0]["categoria"] == "Mascotas" and len(fake.calls) == 1  # mes siguiente: sale de la BBDD


def test_doubt_goes_to_web_then_to_user_and_user_wins(tmp_path):
    c = cfg(tmp_path)
    fake = FakeWebClient({"items": [item(0, "Otros", 0.3)]}, {"items": [item(0, "Compras y retail", 0.5)]})
    movs = [{"descripcion": "TIENDA RARA SPA", "monto": -50000}]
    pend = categorizer.categorize(movs, c, fake, UsageLog())
    assert len(fake.web_calls) == 1  # la web se usa solo para el dudoso
    assert fake.web_calls[0]["tools"][0]["name"] == "web_search"
    assert pend and pend[0]["sugerida"] == "Compras y retail"  # sigue con duda -> te pregunta

    store = categorizer.Clasificaciones(c.data_dir / "clasificaciones.db")
    store.put(pend[0]["clave"], "Hogar y ferreteria", "usuario", 1.0)
    fake2 = FakeWebClient({"items": []}, {"items": []})
    movs2 = [{"descripcion": "TIENDA RARA SPA", "monto": -50000}]
    assert categorizer.categorize(movs2, c, fake2, UsageLog()) == []
    assert movs2[0]["categoria"] == "Hogar y ferreteria" and not fake2.calls and not fake2.web_calls


def test_low_confidence_not_requeried_and_small_amounts_not_asked(tmp_path):
    c = cfg(tmp_path)
    fake = FakeClient({"items": [item(0, "Otros", 0.2)]})
    movs = [{"descripcion": "COSA CHICA", "monto": -3000}]
    assert categorizer.categorize(movs, c, fake, UsageLog(), use_web=False) == []  # bajo el umbral: no molesta
    categorizer.categorize(movs, c, fake, UsageLog(), use_web=False)
    assert len(fake.calls) == 1  # no se vuelve a gastar en IA


def test_tef_by_rut_own_transfers_and_no_llm(tmp_path):
    c = cfg(tmp_path)
    fake = FakeClient({})
    movs = [
        {"descripcion": "TEF 11111111-1 David Esteban G", "monto": 250000},
        {"descripcion": "TEF 11111111-1 David Gonzalez", "monto": -500000},
        {"descripcion": "TEF 53323574-3 Condominio Luis", "monto": -58104},
    ]
    pend = categorizer.categorize(movs, c, fake, UsageLog(), titular="GONZALEZ MONSALVEZ DAVID ESTEBAN")
    assert movs[0]["categoria"] == movs[1]["categoria"] == "Transferencia propia (interno)"  # mismo RUT, distinto nombre
    assert movs[2]["categoria"] == "Vivienda y cuentas basicas"
    assert not fake.calls
    assert [p["clave"] for p in pend] == ["TEF 11111111-1"]  # una sola pregunta por RUT


def test_preguntar_saves_user_answer(tmp_path, monkeypatch):
    c = cfg(tmp_path)
    pend = [{"clave": "TIENDA X", "ejemplo": "TIENDA X", "sugerida": "Otros", "veces": 1, "total": 40000}]
    monkeypatch.setattr("builtins.input", lambda _: str(categorizer.CATEGORIAS.index("Salud") + 1))
    movs = [{"descripcion": "TIENDA X", "monto": -40000, "categoria": "Otros"}]
    assert categorizer.preguntar(c, pend, movs) == 1
    assert movs[0]["categoria"] == "Salud"
    assert categorizer.Clasificaciones(c.data_dir / "clasificaciones.db").get("TIENDA X")["fuente"] == "usuario"


def test_card_payment_is_not_spending_and_refund_nets():
    movs = [
        {"fuente": "cuenta_corriente", "descripcion": "Sueldo", "monto": 2_000_000, "categoria": "Sueldo e ingresos"},
        {"fuente": "cuenta_corriente", "descripcion": "Pago tarjeta", "monto": -500_000, "categoria": categorizer.INTERNO},
        {"fuente": "tarjeta_credito", "descripcion": "JUMBO", "monto": -100_000, "categoria": "Supermercado"},
        {"fuente": "tarjeta_credito", "descripcion": "NOTA DE CREDITO", "monto": 10_000, "categoria": "Supermercado"},
    ]
    agg = analyzer.aggregate(movs)
    assert agg["ingresos"] == 2_000_000
    assert agg["gastos"] == 90_000  # el pago de tarjeta no cuenta; el reembolso resta
    assert agg["gastos_tarjeta"] == 90_000 and agg["gastos_cuenta_corriente"] == 0


CARD = Path(__file__).parent.parent / "Estado-de-Cuenta-Scotiabank-Agosto-2026.xls"


@pytest.mark.skipif(not CARD.exists(), reason="requiere el estado de cuenta real")
def test_real_card_statement_reconciles_with_bank_total():
    d = parse_card_statement(CARD)
    facturado = -sum(m["monto"] for m in d["movimientos"] if m["tipo"] != "pago_tarjeta")
    assert facturado == d["total_facturado_declarado"] == 2_856_272


import os

from reporte.account_parser import parse_account_text

ACCOUNT_TEXT = """No. CTA. MONEDA
1 03/AGO/2026 31/AGO/2026
SR(A): PEREZ GOMEZ JUAN
RESUMEN DE MOVIMIENTOS
SALDO ANTERIOR DEPOSITOS/ABONOS CARGOS/GIROS SALDO ACTUAL
1.000 500 300 1.200
03 / AGO TEF 11111111-1 Ana Soto 00000000 500 1.500
05 / AGO PAGO TARJ.CRED. POR SWE 00000000 300 1.200
"""


def test_account_parser_sign_from_balance_and_validation():
    d = parse_account_text(ACCOUNT_TEXT)
    assert [m["monto"] for m in d["movimientos"]] == [500, -300]
    assert d["valido"] and d["periodo"] == "2026-08" and d["titular"] == "PEREZ GOMEZ JUAN"


PDF = Path(__file__).parent.parent / "CartolaCliente.pdf"


@pytest.mark.skipif(not (PDF.exists() and os.getenv("PDF_PASSWORD")), reason="requiere la cartola real y PDF_PASSWORD")
def test_real_account_statement_reconciles():
    from reporte.account_parser import parse_account_statement

    assert parse_account_statement(PDF, os.environ["PDF_PASSWORD"])["valido"]


# ---------- Google Sheets (servicio simulado) ----------
class FakeSheets:
    """Imita lo minimo de la API de Sheets con un dict en memoria."""

    def __init__(self):
        self.tabs = {}

    def spreadsheets(self):
        outer = self

        class V:
            def get(self, spreadsheetId, range):
                tab = range.split("!")[0]
                return SimpleNamespace(execute=lambda: {"values": outer.tabs.get(tab, [])})

            def clear(self, spreadsheetId, range):
                return SimpleNamespace(execute=lambda: outer.tabs.pop(range.split("!")[0], None))

            def update(self, spreadsheetId, range, valueInputOption, body):
                assert valueInputOption == "RAW"
                return SimpleNamespace(execute=lambda: outer.tabs.__setitem__(range.split("!")[0], body["values"]))

        class S:
            def values(self_inner):
                return V()

            def get(self_inner, spreadsheetId):
                return SimpleNamespace(execute=lambda: {"sheets": [{"properties": {"title": t, "sheetId": i}} for i, t in enumerate(outer.tabs)] or [{"properties": {"title": "x", "sheetId": 99}}]})

            def batchUpdate(self_inner, spreadsheetId, body):
                outer.requests = getattr(outer, "requests", []) + body["requests"]
                return SimpleNamespace(execute=lambda: None)

        return S()


def test_sheets_upsert_is_idempotent_and_keeps_other_months(tmp_path):
    from reporte import sheets_client

    c = Config(data_dir=tmp_path / "data", sheet_id="SID")
    svc = FakeSheets()
    movs = [{"fuente": "tarjeta_credito", "fecha": "2026-08-02", "descripcion": "JUMBO", "monto": -1000, "categoria": "Supermercado", "tipo": "compra"}]
    agg = analyzer.aggregate(movs)
    sheets_client.save_month(c, "2026-07", movs, agg, svc=svc)
    sheets_client.save_month(c, "2026-08", movs, agg, svc=svc)
    sheets_client.save_month(c, "2026-08", movs, agg, svc=svc)  # repetir agosto no duplica
    assert [r[0] for r in svc.tabs["Movimientos"]] == ["periodo", "2026-07", "2026-08"]
    assert [r[0] for r in svc.tabs["Resumen"]] == ["periodo", "2026-07", "2026-08"]
    assert svc.tabs["Categorias"][1] == ["2026-07", "Supermercado", 1000.0]
    assert svc.tabs["Presupuesto"] == [["categoria", "presupuesto_mensual"]]


def test_claude_code_backend_uses_structured_output(tmp_path, monkeypatch):
    import subprocess

    from reporte.llm import ask

    seen = {}

    def fake_run(cmd, input, **kw):
        seen["cmd"], seen["input"] = cmd, input
        out = {"is_error": False, "structured_output": {"ok": 1}, "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1500, "output_tokens": 50}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    c = Config(llm="claude-code")
    log = UsageLog()
    assert ask(None, c, log, "t", "sys", "user text", {"type": "object"}) == {"ok": 1}
    assert seen["cmd"][:2] == ["claude", "-p"] and "--tools" in seen["cmd"] and seen["input"] == "user text"
    assert log.calls[0]["in"] == 1502
    assert "Incluido en tu plan" in log.summary(c)


def test_no_web_search_with_claude_code_backend(tmp_path, monkeypatch):
    import subprocess

    def fake_run(cmd, input, **kw):
        out = {"is_error": False, "structured_output": {"items": [item(0, "Otros", 0.2)]}, "usage": {}}
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    c = Config(llm="claude-code", data_dir=tmp_path / "data")
    client = FakeWebClient({}, {})
    movs = [{"descripcion": "TIENDA RARA", "monto": -90000}]
    pend = categorizer.categorize(movs, c, client, UsageLog(), use_web=True)
    assert client.web_calls == [] and pend  # sin web; queda para preguntarte


def test_teach_and_correct_from_google_sheets(tmp_path):
    """Ciclo completo: el agente publica los comercios, tu eliges una categoria en la planilla, la siguiente corrida la aprende."""
    from reporte import sheets_client

    c = Config(llm="none", data_dir=tmp_path / "data", sheet_id="SID")
    svc = FakeSheets()
    movs = [{"descripcion": "TIENDA RARA SPA", "monto": -50000, "fuente": "tarjeta_credito"},
            {"descripcion": "UNIMARC EL SALVADOR", "monto": -7281, "fuente": "tarjeta_credito"}]
    pend = categorizer.categorize(movs, c, None, UsageLog(), use_llm=False)
    assert [p["clave"] for p in pend] == ["TIENDA RARA SPA"]

    resumen = categorizer.comercios_resumen(movs, c, pend)
    assert [r["estado"] for r in resumen] == ["POR CONFIRMAR", "ok"]  # lo dudoso primero
    sheets_client.push_comercios(c, resumen, categorizer.CATEGORIAS, svc=svc)
    validation = svc.requests[-1]["setDataValidation"]["rule"]["condition"]
    assert validation["type"] == "ONE_OF_LIST" and len(validation["values"]) == len(categorizer.CATEGORIAS)

    # tu eliges en la columna 'corregir_a' (F) de la fila de TIENDA RARA, y una opcion invalida en otra
    tab = svc.tabs["Clasificar"]
    assert tab[0][5] == "corregir_a"
    tab[1][5] = "Hogar y ferreteria"
    tab[2][5] = "categoria inventada"

    filas = sheets_client.pull_corrections(c, svc=svc)
    assert categorizer.aplicar_correcciones(c, filas) == 1  # la invalida se ignora

    movs2 = [{"descripcion": "TIENDA RARA SPA", "monto": -30000, "fuente": "tarjeta_credito"}]
    assert categorizer.categorize(movs2, c, None, UsageLog(), use_llm=False) == []
    assert movs2[0]["categoria"] == "Hogar y ferreteria"  # aprendido: el mes siguiente ya no pregunta


# ---------- Gmail por IMAP + recalculo de meses ----------
def _email_with_pdf(name: str, payload: bytes) -> bytes:
    from email.message import EmailMessage

    em = EmailMessage()
    em["Subject"], em["From"] = "Cartola", "cartolas.info@scotiabank.cl"
    em.set_content("adjunto")
    em.add_attachment(payload, maintype="application", subtype="pdf", filename=name)
    return em.as_bytes()


class FakeImap:
    mails = {b"1": _email_with_pdf("vieja.pdf", b"%PDF-old"), b"2": _email_with_pdf("CartolaCliente.pdf", b"%PDF-new")}
    queries = []

    def __init__(self, host):
        self.host = host

    def login(self, u, p):
        if p != "abcdabcdabcdabcd":
            import imaplib

            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, box, readonly=False):
        return "OK", [b"2"]

    def search(self, charset, *criteria):
        FakeImap.queries.append(criteria)
        return "OK", [b"1 2"]

    def fetch(self, mid, what):
        return "OK", [(b"x", self.mails[mid])]

    def logout(self):
        return "BYE", []


def test_gmail_imap_download_latest_and_password_with_spaces(tmp_path, monkeypatch):
    import imaplib

    from reporte import mail_client

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    p = mail_client.download_statement("yo@gmail.com", "abcd abcd abcd abcd", "from:cartolas.info@scotiabank.cl", tmp_path, (".pdf",))
    assert p.name == "CartolaCliente.pdf" and p.read_bytes() == b"%PDF-new"  # el mas reciente primero
    assert FakeImap.queries[-1][0] == "X-GM-RAW"
    assert mail_client.test_connection("yo@gmail.com", "abcd abcd abcd abcd") is None
    assert "rechazo" in mail_client.test_connection("yo@gmail.com", "mala")


def test_recalcular_mes_applies_corrections_without_reuploading(tmp_path):
    from reporte import pipeline
    from reporte.card_parser import parse_card_statement

    if not CARD.exists():
        pytest.skip("requiere el estado de cuenta real")
    c = Config(llm="none", data_dir=tmp_path / "data", output_dir=tmp_path / "out")
    r = pipeline.procesar(None, CARD, c)
    assert r.periodo == "2026-08" and r.pdf.exists() and pipeline.meses_guardados(c) == ["2026-08"]
    antes = r.agg["gastos_por_categoria"].get("Mascotas", 0)
    categorizer.Clasificaciones(c.data_dir / "clasificaciones.db").put("GRUPO MBO WEB", "Mascotas", "usuario", 1.0)
    r2 = pipeline.recalcular_mes(c, "2026-08")
    assert r2.agg["gastos_por_categoria"]["Mascotas"] == antes + 25493
    assert r2.agg["conciliacion"]["tarjeta"] == 0  # la conciliacion sobrevive al recalculo


def test_recalculo_da_los_mismos_numeros_que_la_primera_corrida(tmp_path):
    """Regresion: al recalcular se perdia el titular y los traspasos propios pasaban a contarse como gasto."""
    from reporte import pipeline

    if not (CARD.exists() and PDF.exists() and os.getenv("PDF_PASSWORD")):
        pytest.skip("requiere las cartolas reales y PDF_PASSWORD")
    c = Config(llm="none", data_dir=tmp_path / "data", output_dir=tmp_path / "out", pdf_password=os.environ["PDF_PASSWORD"])
    r1 = pipeline.procesar(PDF, CARD, c)
    r2 = pipeline.recalcular_mes(c, r1.periodo)
    assert (r2.agg["ingresos"], r2.agg["gastos"]) == (r1.agg["ingresos"], r1.agg["gastos"]) == (3249546, 3251336)
    assert pipeline.cargar_comercios(c, r1.periodo)  # la pantalla Clasificar usa el mismo titular


# ---------- ejecucion automatica ----------
def _auto_env(tmp_path, monkeypatch, cuenta_file, enviados):
    from reporte import ajustes, automatico, mail_client, secrets_store

    c = Config(llm="none", data_dir=tmp_path / "data", output_dir=tmp_path / "out", inbox_dir=tmp_path / "entrada",
               pdf_password=os.getenv("PDF_PASSWORD"))
    monkeypatch.setattr(ajustes, "make_config", lambda base=None: c)
    monkeypatch.setattr(ajustes, "load", lambda cfg: {**ajustes.DEFAULTS, "gmail_email": "yo@gmail.com"})
    monkeypatch.setattr(secrets_store, "get", lambda n: "clave-app" if n == "gmail_app_password" else None)
    monkeypatch.setattr(mail_client, "download_statement", lambda *a, **k: cuenta_file())
    monkeypatch.setattr(mail_client, "send_report", lambda *a, **k: enviados.append(a))
    avisos = []
    monkeypatch.setattr(automatico, "notificar", lambda t, x: avisos.append((t, x)))
    return c, automatico, avisos


def test_automatico_avisa_si_falta_la_tarjeta_y_no_envia_nada_a_medias(tmp_path, monkeypatch):
    enviados = []
    c, automatico, avisos = _auto_env(tmp_path, monkeypatch, lambda: PDF, enviados)
    assert automatico.main([]) == 0
    assert enviados == [] and "falta la tarjeta" in avisos[0][0]


def test_automatico_no_hace_nada_si_aun_no_llega_la_cartola(tmp_path, monkeypatch):
    def no_hay():
        raise FileNotFoundError("sin correos")

    enviados = []
    c, automatico, avisos = _auto_env(tmp_path, monkeypatch, no_hay, enviados)
    assert automatico.main([]) == 0 and enviados == [] and avisos == []


@pytest.mark.skipif(not (CARD.exists() and PDF.exists() and os.getenv("PDF_PASSWORD")), reason="requiere las cartolas reales y PDF_PASSWORD")
def test_automatico_flujo_completo_y_es_idempotente(tmp_path, monkeypatch):
    import shutil

    enviados = []
    c, automatico, avisos = _auto_env(tmp_path, monkeypatch, lambda: PDF, enviados)
    c.inbox_dir.mkdir()
    shutil.copy(CARD, c.inbox_dir / CARD.name)
    assert automatico.main([]) == 0
    assert len(enviados) == 1 and "2026-08" in enviados[0][3]  # asunto del correo
    assert avisos[-1][0] == "Reporte 2026-08 listo"
    assert automatico.main([]) == 0 and len(enviados) == 1  # misma cartola: no reenvia
    assert automatico.main(["--forzar"]) == 0 and len(enviados) == 2


def test_launchd_plist_es_valido(tmp_path):
    import plistlib

    from reporte import launchd

    d = plistlib.loads(plistlib.dumps(launchd.plist_dict("/p/.venv/bin/python", tmp_path)))
    assert d["ProgramArguments"] == ["/p/.venv/bin/python", "-m", "reporte.automatico"]
    assert [x["Day"] for x in d["StartCalendarInterval"]] == [2, 3, 4, 5, 6, 7, 8]
    assert d["EnvironmentVariables"]["PYTHONPATH"].endswith("src")
