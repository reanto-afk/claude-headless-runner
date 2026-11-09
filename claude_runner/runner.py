"""Uma execução de rotina: tentativas, retry só no que é transitório, histórico e alerta."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from . import alert as alert_mod
from .claude import Attempt, invoke
from .config import Routine
from .state import StateDir

HUMAN = {
    "run_failed": "a própria rotina reportou falha: {detail}",
    "contract": "a rotina terminou sem RUN_OK / RUN_FAILED na última linha ({detail}); revise o prompt",
    "auth": "o login do Claude venceu ou é inválido; abra `claude` na máquina da rotina e faça /login",
    "rate_limit": "limite de uso do Claude atingido; a rotina tenta de novo no próximo horário",
    "overloaded": "a API do Claude está instável ({detail})",
    "timeout": "não terminou em {timeout}s",
    "max_turns": "atingiu o limite de turnos sem concluir",
    "crash": "o claude saiu com erro: {detail}",
    "setup": "não consegui rodar o claude: {detail}",
    "overlap": "a execução anterior ainda está rodando (ou travou); esta foi pulada",
}


def human_message(routine: Routine, attempt: Attempt, attempts: int) -> str:
    msg = HUMAN.get(attempt.kind, "{detail}").format(detail=attempt.detail, timeout=routine.timeout_seconds)
    return msg + (f" (após {attempts} tentativas)" if attempts > 1 else "")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def run_routine(routine: Routine, claude_cmd: list[str] | None = None, now: Callable[[], float] = time.time,
                sleep: Callable[[float], None] = time.sleep, notify: Callable[..., str | None] | None = None) -> dict:
    notify = notify or alert_mod.send
    state = StateDir(routine.state_dir)
    started = now()
    attempts: list[Attempt] = []

    with state.single_instance(stale_after=routine.max_runtime_seconds + 60) as acquired:
        if not acquired:
            attempts.append(Attempt("overlap", "trava de execução ativa"))
        else:
            prompt = routine.prompt_file.read_text(encoding="utf-8")
            for i in range(routine.max_attempts):
                attempts.append(invoke(routine, prompt, claude_cmd))
                last = attempts[-1]
                if last.kind not in routine.retry_on or i == routine.max_attempts - 1:
                    break
                sleep(routine.backoff_seconds[min(i, len(routine.backoff_seconds) - 1)] if routine.backoff_seconds else 0)

        final = attempts[-1]
        finished = now()
        run = {
            "routine": routine.name, "kind": final.kind, "started_at": _iso(started), "finished_at": _iso(finished),
            "duration_s": round(finished - started, 1), "attempts": [a.to_dict() for a in attempts],
            "cost_usd": round(sum(a.cost_usd or 0 for a in attempts), 6),
            "session_id": final.session_id, "message": "", "alert_error": None,
        }
        if final.kind == "ok":
            run["message"] = "RUN_OK"
            if routine.alert.notify_on_success:
                body = "\n".join(final.result.strip().splitlines()[:-1]).strip() or "(sem texto)"
                run["alert_error"] = notify(routine.alert, f"[{routine.name}] ok", body)
        else:
            run["message"] = human_message(routine, final, len(attempts))
            run["alert_error"] = notify(routine.alert, f"[{routine.name}] FALHOU", run["message"])
        if acquired:
            state.record(run)
    return run
