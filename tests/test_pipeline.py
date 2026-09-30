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
    return Config(data_dir=tmp_path / "data", output_dir=tmp_path / "out")


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
