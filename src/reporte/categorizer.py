"""Clasificador que aprende: cada comercio se clasifica una vez y queda en una BBDD.

Escalera por comercio (se detiene en el primer paso que resuelve):
  1. BBDD, clasificacion confirmada por ti        (fuente 'usuario')  -> gratis, siempre manda
  2. Reglas por palabra clave (reglas_categorias.json)                -> gratis
  3. BBDD, clasificacion previa de IA/web con confianza alta          -> gratis
  4. IA (un solo llamado por lote, con confianza 0-1)                 -> centavos
  5. Busqueda web para lo que la IA dejo con duda                     -> opcional
  6. Preguntarte a ti (interactivo) o dejarlo en data/pendientes.json -> tu respuesta queda como 'usuario'
Las transferencias a personas (TEF) no se mandan a la IA ni a la web: se clasifican por RUT y se te preguntan
solo si el monto acumulado es relevante.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

from .config import Config
from .llm import UsageLog, ask, ask_web

CATEGORIAS = [
    "Supermercado", "Restaurantes y delivery", "Transporte y bencina", "Vivienda y cuentas basicas",
    "Salud", "Educacion", "Entretenimiento y suscripciones", "Compras y retail", "Hogar y ferreteria",
    "Mascotas", "Viajes", "Seguros", "Deuda y creditos", "Impuestos", "Comisiones e intereses bancarios",
    "Pagos digitales sin detalle", "Transferencias enviadas", "Sueldo e ingresos",
    "Transferencias recibidas", "Ahorro e inversion", "Pago tarjeta (interno)",
    "Transferencia propia (interno)", "Otros",
]
INTERNO = "Pago tarjeta (interno)"
INTERNOS = {INTERNO, "Transferencia propia (interno)"}  # mueven plata entre tus cuentas: no son gasto ni ingreso
INGRESOS = {"Sueldo e ingresos", "Transferencias recibidas"}

RULES_FILE = Path(__file__).with_name("reglas_categorias.json")
CONF_OK = 0.8

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "categoria": {"type": "string", "enum": CATEGORIAS},
                    "confianza": {"type": "number", "description": "0 a 1"},
                    "motivo": {"type": "string", "description": "Maximo 12 palabras"},
                },
                "required": ["id", "categoria", "confianza", "motivo"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM = (
    "Clasificas movimientos bancarios chilenos en las categorias permitidas. Para cada item recibes la descripcion "
    "tal como sale en la cartola, el signo (gasto o abono) y un monto de ejemplo. 'confianza' es tu certeza real: "
    "usa menos de 0.8 si no reconoces el comercio o hay mas de una categoria plausible. No inventes."
)


def norm(desc: str) -> str:
    d = desc.upper()
    d = re.sub(r"TASA INT.*$", "", d)
    d = re.sub(r"\d{6,}K?", "", d)  # ruts / ids de comercio
    return re.sub(r"\s+", " ", d).strip()


def key_of(desc: str) -> str:
    """Las TEF se identifican por RUT (el nombre cambia: 'David Esteban G' / 'David Gonzalez')."""
    m = re.match(r"TEF\s+(\d{7,8}-[\dK])", desc.upper())
    return f"TEF {m.group(1)}" if m else norm(desc)


class Clasificaciones:
    """BBDD SQLite de clasificaciones aprendidas."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS comercios (clave TEXT PRIMARY KEY, categoria TEXT NOT NULL, "
            "fuente TEXT NOT NULL, confianza REAL NOT NULL, motivo TEXT, ejemplo TEXT, "
            "actualizado TEXT DEFAULT CURRENT_TIMESTAMP)"
        )

    def get(self, clave: str):
        r = self.db.execute("SELECT categoria, fuente, confianza FROM comercios WHERE clave=?", (clave,)).fetchone()
        return dict(zip(("categoria", "fuente", "confianza"), r)) if r else None

    def put(self, clave, categoria, fuente, confianza, motivo="", ejemplo=""):
        self.db.execute(
            "INSERT INTO comercios(clave, categoria, fuente, confianza, motivo, ejemplo) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(clave) DO UPDATE SET categoria=excluded.categoria, fuente=excluded.fuente, "
            "confianza=excluded.confianza, motivo=excluded.motivo, actualizado=CURRENT_TIMESTAMP",
            (clave, categoria, fuente, confianza, motivo, ejemplo),
        )
        self.db.commit()


def _by_rules(key: str, rules) -> str | None:
    return next((cat for kw, cat in rules if kw in key), None)


def _web_pass(client, cfg, log, items: list[dict]) -> dict[int, dict]:
    """Busca en internet los comercios dudosos. Solo se envian nombres de comercio (nunca RUT ni personas)."""
    listing = "\n".join(f"{it['id']}: {it['descripcion']}" for it in items)
    prompt = (
        "Busca en internet que tipo de comercio/servicio es cada descripcion de cartola bancaria chilena y clasificalo. "
        f"Categorias permitidas: {', '.join(CATEGORIAS)}.\n\n{listing}\n\n"
        'Responde SOLO un JSON: {"items":[{"id":0,"categoria":"...","confianza":0.0,"motivo":"..."}]}. '
        "Confianza < 0.8 si no pudiste confirmarlo."
    )
    text = ask_web(client, cfg, log, "busqueda web", prompt, max_uses=min(2 * len(items), 10))
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return {i["id"]: i for i in json.loads(m.group(0))["items"] if i["categoria"] in CATEGORIAS} if m else {}
    except (json.JSONDecodeError, KeyError):
        return {}


def _es_propia(desc: str, titular: str | None) -> bool:
    """TEF cuyo nombre coincide (>=2 palabras) con el titular de la cuenta: probable traspaso entre cuentas propias."""
    if not titular:
        return False
    words = lambda t: {w for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in ("tef", "spa")}  # noqa: E731
    return len(words(desc) & words(titular)) >= 2


def categorize(movs: list[dict], cfg: Config, client, log: UsageLog, use_llm: bool = True, use_web: bool = True,
               titular: str | None = None) -> list[dict]:
    """Asigna m['categoria'] y devuelve la lista de pendientes (dudas para el usuario)."""
    rules = json.loads(RULES_FILE.read_text())["reglas"]
    store = Clasificaciones(cfg.data_dir / "clasificaciones.db")

    groups: dict[str, list[dict]] = {}
    for m in movs:
        groups.setdefault(key_of(m["descripcion"]), []).append(m)

    resolved: dict[str, tuple[str, str]] = {}  # clave -> (categoria, estado) estado: ok | duda
    to_ai: list[str] = []
    for key, ms in groups.items():
        if all(m.get("tipo") == "pago_tarjeta" for m in ms):
            resolved[key] = (INTERNO, "ok")
            continue
        row = store.get(key)
        if row and row["fuente"] == "usuario":
            resolved[key] = (row["categoria"], "ok")
        elif cat := _by_rules(key, rules) or _by_rules(norm(ms[0]["descripcion"]), rules):
            resolved[key] = (cat, "ok")
        elif row and row["confianza"] >= CONF_OK:
            resolved[key] = (row["categoria"], "ok")
        elif row:  # ya lo vio la IA con duda: no se vuelve a pagar, queda pendiente para ti
            resolved[key] = (row["categoria"], "duda")
        elif key.startswith("TEF "):
            total = sum(m["monto"] for m in ms)
            if _es_propia(ms[0]["descripcion"], titular):
                resolved[key] = ("Transferencia propia (interno)", "duda")  # sugerida; confirmala una vez
            else:
                resolved[key] = ("Transferencias recibidas" if total > 0 else "Transferencias enviadas", "duda")
        else:
            to_ai.append(key)

    if to_ai and use_llm:
        items = [{"id": i, "clave": k, "descripcion": groups[k][0]["descripcion"],
                  "tipo": "abono" if groups[k][0]["monto"] > 0 else "gasto", "monto": abs(groups[k][0]["monto"])}
                 for i, k in enumerate(to_ai)]
        listing = "\n".join(f"{it['id']}: {it['descripcion']} | {it['tipo']} | ${it['monto']:.0f}" for it in items)
        res = {r["id"]: r for r in ask(client, cfg, log, "clasificar (IA)", SYSTEM, listing, SCHEMA, max_tokens=6000)["items"]}

        dudosos = [it for it in items if it["id"] in res and res[it["id"]]["confianza"] < CONF_OK]
        web = _web_pass(client, cfg, log, dudosos) if dudosos and use_web and cfg.llm == "api" and client is not None else {}
        for it in items:
            r, fuente = res.get(it["id"]), "ia"
            if it["id"] in web and web[it["id"]]["confianza"] >= (r["confianza"] if r else 0):
                r, fuente = web[it["id"]], "web"
            if not r:
                continue
            store.put(it["clave"], r["categoria"], fuente, r["confianza"], r.get("motivo", ""), it["descripcion"])
            resolved[it["clave"]] = (r["categoria"], "ok" if r["confianza"] >= CONF_OK else "duda")

    pendientes = []
    for key, ms in groups.items():
        cat, estado = resolved.get(key, ("Otros", "duda"))
        for m in ms:
            m["categoria"] = cat
        total = sum(abs(m["monto"]) for m in ms)
        if estado == "duda" and total >= cfg.ask_min_amount:
            pendientes.append({"clave": key, "ejemplo": ms[0]["descripcion"], "sugerida": cat,
                               "veces": len(ms), "total": total})
    pendientes.sort(key=lambda p: -p["total"])
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "pendientes.json").write_text(json.dumps(pendientes, ensure_ascii=False, indent=1))
    return pendientes


def preguntar(cfg: Config, pendientes: list[dict], movs: list[dict] | None = None) -> int:
    """Pregunta por consola; cada respuesta queda como 'usuario' y manda sobre todo lo demas."""
    store = Clasificaciones(cfg.data_dir / "clasificaciones.db")
    hechos = 0
    for n, p in enumerate(pendientes, 1):
        print(f"\n[{n}/{len(pendientes)}] {p['ejemplo']}  ({p['veces']} mov., total ${p['total']:,.0f})".replace(",", "."))
        print(f"  Sugerida: {p['sugerida']}")
        for i, c in enumerate(CATEGORIAS, 1):
            print(f"  {i:>2}. {c}")
        resp = input("  Numero de categoria, Enter = aceptar sugerida, s = saltar: ").strip().lower()
        if resp == "s":
            continue
        cat = p["sugerida"] if resp == "" else CATEGORIAS[int(resp) - 1] if resp.isdigit() and 1 <= int(resp) <= len(CATEGORIAS) else None
        if cat is None:
            print("  Opcion invalida, se salta.")
            continue
        store.put(p["clave"], cat, "usuario", 1.0, "confirmado por el usuario", p["ejemplo"])
        hechos += 1
        for m in movs or []:
            if key_of(m["descripcion"]) == p["clave"]:
                m["categoria"] = cat
    return hechos


def es_interactivo() -> bool:
    return sys.stdin.isatty()
