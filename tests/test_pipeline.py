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


def test_rules_and_cache_avoid_llm(tmp_path):
    movs = [{"descripcion": "UNIMARC EL SALVADOR", "monto": -7281}, {"descripcion": "MERPAGO*P 995442205 995442205", "monto": -1590}]
    log = UsageLog()
    assert categorizer.categorize(movs, cfg(tmp_path), FakeClient({}), log) == []
    assert [m["categoria"] for m in movs] == ["Supermercado", "Pagos digitales sin detalle"]
    assert log.calls == []  # 0 llamadas: todo resuelto por reglas


def test_unknown_merchant_goes_to_llm_once_then_cached(tmp_path):
    c = cfg(tmp_path)
    fake = FakeClient({"categorias": [{"id": 0, "categoria": "Mascotas"}]})
    movs = [{"descripcion": "VETERINARIA XYZ", "monto": -20000}]
    categorizer.categorize(movs, c, fake, UsageLog())
    assert movs[0]["categoria"] == "Mascotas" and len(fake.calls) == 1
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"
    assert fake.calls[0]["output_config"]["effort"] == "low"
    movs2 = [{"descripcion": "VETERINARIA XYZ", "monto": -5000}]
    categorizer.categorize(movs2, c, fake, UsageLog())
    assert movs2[0]["categoria"] == "Mascotas" and len(fake.calls) == 1  # segundo mes: desde cache


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
