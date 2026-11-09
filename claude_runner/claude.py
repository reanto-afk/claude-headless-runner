"""Chama o `claude -p` e classifica o resultado."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass

from .config import Routine


@dataclass
class Attempt:
    kind: str
    detail: str = ""
    returncode: int | None = None
    session_id: str | None = None
    cost_usd: float | None = None
    duration_s: float = 0.0
    result: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# --- contrato de saída -----------------------------------------------------------------------

def check_contract(text: str) -> tuple[str, str]:
    """A última linha não vazia precisa ser RUN_OK ou RUN_FAILED: motivo."""
    lines = [ln.strip().strip("`*_ ") for ln in (text or "").splitlines() if ln.strip().strip("`*_ ")]
    last = lines[-1] if lines else ""
    if last == "RUN_OK":
        return "ok", ""
    if last.startswith("RUN_FAILED"):
        reason = last[len("RUN_FAILED"):].lstrip(" :-—").strip()
        return "run_failed", reason or "sem motivo informado"
    return "contract", f"última linha: {last[:120]!r}" if last else "resposta vazia"


# --- classificação de erro -------------------------------------------------------------------

AUTH_HINTS = ("/login", "invalid api key", "oauth token", "not logged in", "authentication", "credential")
LIMIT_HINTS = ("rate limit", "rate_limit", "usage limit", "limit reached", "limit will reset")
OVERLOAD_HINTS = ("overloaded", "internal server error", "service unavailable", "bad gateway")


def kind_from(status: int | None, text: str) -> str:
    t = text.lower()
    if status in (401, 403) or any(h in t for h in AUTH_HINTS):
        return "auth"
    if status == 429 or any(h in t for h in LIMIT_HINTS):
        return "rate_limit"
    if (status is not None and status >= 500) or any(h in t for h in OVERLOAD_HINTS):
        return "overloaded"
    return "crash"


def parse_json(stdout: str) -> dict | None:
    text = stdout.strip()
    for candidate in (text, text.splitlines()[-1] if text else ""):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, IndexError):
            continue
        if isinstance(data, dict) and data.get("type") == "result":
            return data
    return None


def classify(returncode: int | None, stdout: str, stderr: str) -> Attempt:
    data = parse_json(stdout)
    if data is None:
        text = (stderr or stdout).strip()
        return Attempt(kind_from(None, text), text[-300:] or f"saída vazia (código {returncode})", returncode)
    common = dict(returncode=returncode, session_id=data.get("session_id"),
                  cost_usd=data.get("total_cost_usd"), result=str(data.get("result") or ""))
    if not data.get("is_error") and data.get("subtype") == "success":
        kind, detail = check_contract(common["result"])
        return Attempt(kind, detail, **common)
    if data.get("subtype") == "error_max_turns":
        return Attempt("max_turns", "limite de turnos atingido", **common)
    status = data.get("api_error_status")
    text = f"{common['result']} {stderr}"
    return Attempt(kind_from(status if isinstance(status, int) else None, text),
                   (f"HTTP {status}: " if status else "") + text.strip()[-300:], **common)


# --- execução --------------------------------------------------------------------------------

def resolve_claude(explicit: list[str] | None = None) -> list[str]:
    if explicit:
        return list(explicit)
    name = os.environ.get("CLAUDE_RUNNER_CLAUDE_BIN", "claude")
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"'{name}' não encontrado no PATH")
    return [found]


def build_command(routine: Routine, claude_cmd: list[str]) -> list[str]:
    cmd = [*claude_cmd, "-p", "--output-format", "json"]
    if routine.model:
        cmd += ["--model", routine.model]
    cmd += list(routine.extra_args)
    if routine.allowed_tools:  # opção variádica: fica por último; o prompt vai pelo stdin
        cmd += ["--allowedTools", *routine.allowed_tools]
    return cmd


def _kill_tree(proc: subprocess.Popen) -> None:
    """Mata o processo e os filhos (o claude roda em node, que pode deixar órfãos)."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, OSError):
        pass
    proc.kill()


def invoke(routine: Routine, prompt: str, claude_cmd: list[str] | None = None) -> Attempt:
    started = time.monotonic()
    try:
        cmd = build_command(routine, resolve_claude(claude_cmd))
    except FileNotFoundError as exc:
        return Attempt("setup", str(exc))
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if sys.platform == "win32"
             else {"start_new_session": True})
    try:
        proc = subprocess.Popen(cmd, cwd=routine.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, **group)
    except OSError as exc:
        return Attempt("setup", f"não consegui iniciar o claude: {exc}")
    try:
        out, err = proc.communicate(prompt.encode("utf-8"), timeout=routine.timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        return Attempt("timeout", f"passou de {routine.timeout_seconds}s", None,
                       duration_s=round(time.monotonic() - started, 1))
    attempt = classify(proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))
    attempt.duration_s = round(time.monotonic() - started, 1)
    return attempt
