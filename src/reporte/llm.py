"""Llamada a Claude con salida JSON estructurada y registro de tokens/costo."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from types import SimpleNamespace

from .config import Config


@dataclass
class UsageLog:
    calls: list[dict] = field(default_factory=list)

    def add(self, label: str, usage) -> None:
        self.calls.append({
            "label": label,
            "in": usage.input_tokens + (getattr(usage, "cache_read_input_tokens", 0) or 0),
            "out": usage.output_tokens,
        })

    def summary(self, cfg: Config) -> str:
        if not self.calls:
            return "Uso de IA: 0 llamadas (costo $0)."
        if cfg.llm == "claude-code":
            t_in, t_out = sum(c["in"] for c in self.calls), sum(c["out"] for c in self.calls)
            return (f"Uso de IA via Claude Code: {len(self.calls)} llamada(s), {t_in} tokens de entrada, {t_out} de salida. "
                    "Incluido en tu plan; sin costo adicional.")
        lines = []
        tot_in = tot_out = 0
        for c in self.calls:
            cost = c["in"] / 1e6 * cfg.price_in + c["out"] / 1e6 * cfg.price_out
            lines.append(f"  {c['label']:<22} in={c['in']:>7} out={c['out']:>6}  ~US${cost:.4f}")
            tot_in += c["in"]
            tot_out += c["out"]
        total = tot_in / 1e6 * cfg.price_in + tot_out / 1e6 * cfg.price_out
        return f"Uso de LLM ({cfg.model}, effort={cfg.effort}):\n" + "\n".join(lines) + f"\n  TOTAL ~US${total:.4f}"


def ask(client, cfg: Config, log: UsageLog, label: str,
        system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict:
    if cfg.llm == "claude-code":
        return _ask_claude_code(cfg, log, label, system, user, schema)
    return _ask_api(client, cfg, log, label, system, user, schema, max_tokens)


def _ask_claude_code(cfg: Config, log: UsageLog, label: str, system: str, user: str, schema: dict) -> dict:
    """Usa tu plan de Claude a traves de Claude Code en modo no interactivo (`claude -p`).

    Sin herramientas y con prompt de sistema propio: el contexto baja de ~32.000 a ~1.500 tokens por llamada.
    """
    cmd = ["claude", "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
           "--system-prompt", system, "--no-session-persistence", "--tools", ""]
    if cfg.claude_code_model:
        cmd += ["--model", cfg.claude_code_model]
    try:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=600)
    except FileNotFoundError:
        raise SystemExit("No se encontro el comando `claude`. Instala Claude Code e inicia sesion con tu cuenta, o usa REPORTE_LLM=none.")
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p fallo en '{label}': {proc.stderr.strip()[:300]}")
    d = json.loads(proc.stdout)
    if d.get("is_error") or d.get("structured_output") is None:
        raise RuntimeError(f"claude -p sin resultado en '{label}': {str(d.get('result'))[:300]}")
    u = d.get("usage", {})
    log.add(label, SimpleNamespace(
        input_tokens=u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=u.get("cache_read_input_tokens", 0), output_tokens=u.get("output_tokens", 0)))
    return d["structured_output"]


def _ask_api(client, cfg: Config, log: UsageLog, label: str,
             system: str, user: str, schema: dict, max_tokens: int = 8000) -> dict:
    # Streaming evita timeouts en extracciones largas; para respuestas cortas no cambia el costo.
    with client.messages.stream(
        model=cfg.model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": cfg.effort, "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    log.add(label, msg.usage)
    if msg.stop_reason == "refusal":
        raise RuntimeError("El modelo rechazo la solicitud.")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError(f"Respuesta truncada en '{label}'. Sube max_tokens o divide la entrada.")
    return json.loads(next(b.text for b in msg.content if b.type == "text"))


def ask_web(client, cfg: Config, log: UsageLog, label: str, prompt: str, max_uses: int = 5) -> str | None:
    """Pregunta con la herramienta de busqueda web de Anthropic. Devuelve el texto final o None si falla."""
    import anthropic

    messages = [{"role": "user", "content": prompt}]
    try:
        for _ in range(4):  # la busqueda del servidor puede pausar el turno (pause_turn)
            msg = client.messages.create(
                model=cfg.model, max_tokens=4000,
                tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}],
                output_config={"effort": cfg.effort}, messages=messages,
            )
            log.add(label, msg.usage)
            if msg.stop_reason != "pause_turn":
                break
            messages = [messages[0], {"role": "assistant", "content": msg.content}]
        return "".join(b.text for b in msg.content if b.type == "text")
    except anthropic.APIError as e:  # busqueda no habilitada en la organizacion, limite, etc.
        print(f"AVISO: la busqueda web no esta disponible ({type(e).__name__}); se sigue sin ella.")
        return None
