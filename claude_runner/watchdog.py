"""Vigia: avisa quando uma rotina passou da janela esperada sem nenhum sucesso.

Pega o que o runner sozinho não vê: tarefa desligada no agendador, máquina desligada, runner que nem iniciou.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from . import alert as alert_mod
from .config import Routine
from .state import StateDir

REMIND_EVERY_S = 24 * 3600


def _parse(iso: str | None) -> float | None:
    return datetime.fromisoformat(iso).timestamp() if iso else None


def check(routine: Routine, now: float, notify: Callable[..., str | None] | None = None) -> str | None:
    """Devolve a mensagem de alerta enviada (ou None)."""
    if not routine.expect_every_hours:
        return None
    notify = notify or alert_mod.send
    state = StateDir(routine.state_dir)
    wd = state.read_watchdog()
    if "first_seen" not in wd:
        wd["first_seen"] = now
        state.write_watchdog(wd)
    last_ok = _parse(state.read_last().get("last_success_at"))
    reference = last_ok or wd["first_seen"]
    if now - reference <= routine.expect_every_hours * 3600:
        return None
    if routine.business_hours:
        start, end = routine.business_hours
        if not start <= datetime.fromtimestamp(now).hour < end:
            return None
    if wd.get("alerted_for") == reference and now - wd.get("alerted_at", 0) < REMIND_EVERY_S:
        return None
    since = (f"desde {datetime.fromtimestamp(last_ok):%d/%m %H:%M}" if last_ok
             else "desde que o vigia começou a acompanhar")
    msg = (f"sem execução com sucesso {since} (esperado a cada {routine.expect_every_hours:g}h). "
           f"Confira se a tarefa do agendador está ativa e se a máquina está ligada.")
    notify(routine.alert, f"[{routine.name}] VIGIA", msg)
    wd.update(alerted_for=reference, alerted_at=now)
    state.write_watchdog(wd)
    return msg


def check_all(routines: list[Routine], now: float | None = None, notify=None) -> list[tuple[str, str]]:
    now = now if now is not None else time.time()
    return [(r.name, m) for r in routines if (m := check(r, now, notify))]
