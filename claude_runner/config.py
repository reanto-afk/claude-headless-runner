"""Leitura e validação de uma rotina (arquivo TOML)."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("ok", "run_failed", "contract", "auth", "rate_limit", "overloaded", "timeout",
         "max_turns", "crash", "setup", "overlap")
DEFAULT_RETRY_ON = ("overloaded", "timeout", "crash")
ALERT_FORMATS = ("slack", "discord", "ntfy")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Alert:
    webhook_env: str = "CLAUDE_RUNNER_WEBHOOK"  # nome da variável; a URL nunca fica no arquivo
    format: str = "slack"
    notify_on_success: bool = False


@dataclass(frozen=True)
class Routine:
    name: str
    path: Path
    prompt_file: Path
    cwd: Path
    state_dir: Path
    model: str | None = None
    allowed_tools: tuple[str, ...] = ()
    extra_args: tuple[str, ...] = ()
    timeout_seconds: int = 600
    max_attempts: int = 2
    backoff_seconds: tuple[int, ...] = (30,)
    retry_on: tuple[str, ...] = DEFAULT_RETRY_ON
    expect_every_hours: float | None = None
    business_hours: tuple[int, int] | None = None
    daily_at: str | None = None
    weekly_at: str | None = None
    every_minutes: int | None = None
    alert: Alert = field(default_factory=Alert)

    @property
    def max_runtime_seconds(self) -> int:
        """Pior caso de uma execução inteira (todas as tentativas e esperas)."""
        waits = sum(self.backoff_seconds[min(i, len(self.backoff_seconds) - 1)]
                    for i in range(self.max_attempts - 1)) if self.backoff_seconds else 0
        return self.timeout_seconds * self.max_attempts + waits


_TOP_KEYS = {"name", "prompt_file", "cwd", "state_dir", "model", "allowed_tools", "extra_args",
             "timeout_seconds", "max_attempts", "backoff_seconds", "retry_on", "expect_every_hours",
             "business_hours", "daily_at", "weekly_at", "every_minutes", "alert"}


def _positive_int(data: dict, key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ConfigError(f"{key} deve ser inteiro >= 1")
    return value


def _str_tuple(data: dict, key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} deve ser lista de textos")
    return tuple(value)


def parse_routine(data: dict, path: Path) -> Routine:
    unknown = set(data) - _TOP_KEYS
    if unknown:
        raise ConfigError(f"chave(s) desconhecida(s): {', '.join(sorted(unknown))}")
    base = path.parent
    name = data.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", name):
        raise ConfigError("name obrigatório: minúsculas, números e hífen")
    prompt = data.get("prompt_file")
    if not isinstance(prompt, str):
        raise ConfigError("prompt_file obrigatório")
    prompt_path = (base / prompt).resolve()
    if not prompt_path.is_file():
        raise ConfigError(f"prompt_file não existe: {prompt_path}")
    cwd = (base / data.get("cwd", ".")).resolve()
    if not cwd.is_dir():
        raise ConfigError(f"cwd não existe: {cwd}")
    env_state = os.environ.get("CLAUDE_RUNNER_STATE")
    state_dir = (Path(env_state) / name) if env_state else (base / data.get("state_dir", ".runner-state")).resolve()

    backoff = data.get("backoff_seconds", [30])
    if not isinstance(backoff, list) or not all(isinstance(b, int) and b >= 0 for b in backoff):
        raise ConfigError("backoff_seconds deve ser lista de inteiros >= 0")
    retry_on = _str_tuple(data, "retry_on") if "retry_on" in data else DEFAULT_RETRY_ON
    bad = set(retry_on) - set(KINDS)
    if bad:
        raise ConfigError(f"retry_on com tipo desconhecido: {sorted(bad)}")

    expect = data.get("expect_every_hours")
    if expect is not None and (not isinstance(expect, (int, float)) or expect <= 0):
        raise ConfigError("expect_every_hours deve ser > 0")
    hours = data.get("business_hours")
    business = None
    if hours is not None:
        m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", str(hours))
        if not m or not 0 <= int(m[1]) < int(m[2]) <= 24:
            raise ConfigError('business_hours no formato "8-18"')
        business = (int(m[1]), int(m[2]))
    daily_at = data.get("daily_at")
    if daily_at is not None and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(daily_at)):
        raise ConfigError('daily_at no formato "HH:MM"')
    every = data.get("every_minutes")
    if every is not None and (not isinstance(every, int) or not 1 <= every <= 1439):
        raise ConfigError("every_minutes entre 1 e 1439")
    weekly_at = data.get("weekly_at")
    if weekly_at is not None and not re.fullmatch(r"(MON|TUE|WED|THU|FRI|SAT|SUN) ([01]\d|2[0-3]):[0-5]\d", str(weekly_at)):
        raise ConfigError('weekly_at no formato "FRI 16:00"')
    if sum(x is not None for x in (daily_at, weekly_at, every)) > 1:
        raise ConfigError("use só um de daily_at, weekly_at ou every_minutes")

    raw_alert = data.get("alert", {})
    if not isinstance(raw_alert, dict) or set(raw_alert) - {"webhook_env", "format", "notify_on_success"}:
        raise ConfigError("[alert] aceita webhook_env, format, notify_on_success")
    alert = Alert(
        webhook_env=str(raw_alert.get("webhook_env", "CLAUDE_RUNNER_WEBHOOK")),
        format=str(raw_alert.get("format", "slack")),
        notify_on_success=bool(raw_alert.get("notify_on_success", False)),
    )
    if alert.format not in ALERT_FORMATS:
        raise ConfigError(f"alert.format deve ser um de {ALERT_FORMATS}")

    model = data.get("model")
    return Routine(
        name=name, path=path.resolve(), prompt_file=prompt_path, cwd=cwd, state_dir=state_dir,
        model=str(model) if model else None,
        allowed_tools=_str_tuple(data, "allowed_tools"), extra_args=_str_tuple(data, "extra_args"),
        timeout_seconds=_positive_int(data, "timeout_seconds", 600),
        max_attempts=_positive_int(data, "max_attempts", 2),
        backoff_seconds=tuple(backoff), retry_on=retry_on,
        expect_every_hours=float(expect) if expect is not None else None,
        business_hours=business, daily_at=daily_at, weekly_at=weekly_at, every_minutes=every, alert=alert,
    )


def load_routine(path: str | os.PathLike) -> Routine:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"rotina não encontrada: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML inválido em {path}: {exc}") from exc
    return parse_routine(data, path)


def discover(paths: list[str]) -> list[Path]:
    """Arquivos de rotina: caminhos .toml diretos ou todo `routine.toml` dentro de pastas."""
    found: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            found.extend(sorted(q for q in p.rglob("routine.toml") if ".runner-state" not in q.parts))
        else:
            found.append(p)
    return found
