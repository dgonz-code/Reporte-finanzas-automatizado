"""Llamada a Claude con salida JSON estructurada y registro de tokens/costo."""
import json
from dataclasses import dataclass, field

import anthropic

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
            return "Uso de LLM: 0 llamadas (costo $0)."
        lines = []
        tot_in = tot_out = 0
        for c in self.calls:
            cost = c["in"] / 1e6 * cfg.price_in + c["out"] / 1e6 * cfg.price_out
            lines.append(f"  {c['label']:<22} in={c['in']:>7} out={c['out']:>6}  ~US${cost:.4f}")
            tot_in += c["in"]
            tot_out += c["out"]
        total = tot_in / 1e6 * cfg.price_in + tot_out / 1e6 * cfg.price_out
        return f"Uso de LLM ({cfg.model}, effort={cfg.effort}):\n" + "\n".join(lines) + f"\n  TOTAL ~US${total:.4f}"


def ask(client: anthropic.Anthropic, cfg: Config, log: UsageLog, label: str,
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


def ask_web(client: anthropic.Anthropic, cfg: Config, log: UsageLog, label: str, prompt: str, max_uses: int = 5) -> str | None:
    """Pregunta con la herramienta de busqueda web de Anthropic. Devuelve el texto final o None si falla."""
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
