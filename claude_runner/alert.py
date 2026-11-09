"""Envio de alerta por webhook (Slack, Discord ou ntfy). Nunca levanta exceção."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

from .config import Alert

LIMITS = {"slack": 3500, "discord": 1900, "ntfy": 3500}


def send(alert: Alert, title: str, body: str) -> str | None:
    """Envia; devolve None se deu certo ou o motivo da falha (que vai para o histórico e o stderr)."""
    url = os.environ.get(alert.webhook_env)
    text = f"{title}\n{body}".strip()[: LIMITS[alert.format]]
    if not url:
        print(f"[claude-runner] ALERTA (webhook não configurado em {alert.webhook_env}): {text}", file=sys.stderr)
        return f"webhook não configurado ({alert.webhook_env})"
    if alert.format == "ntfy":
        data, headers = body.encode("utf-8"), {"Title": title}  # título é ASCII: nome da rotina é validado
    else:
        key = "text" if alert.format == "slack" else "content"
        data, headers = json.dumps({key: text}).encode("utf-8"), {"Content-Type": "application/json"}
    headers["User-Agent"] = "claude-headless-runner"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=10):
            return None
    except Exception as exc:  # alerta que falha não pode derrubar a rotina, mas fica registrado
        print(f"[claude-runner] falha ao enviar alerta: {exc}\n{text}", file=sys.stderr)
        return f"falha ao enviar alerta: {type(exc).__name__}: {exc}"
