"""Gera (sem registrar) a linha de crontab e o comando do Agendador de Tarefas do Windows."""
from __future__ import annotations

import sys

from .config import ConfigError, Routine

CRON_DAYS = {"SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6}


def run_command(routine: Routine, python: str | None = None) -> str:
    return f'"{python or sys.executable}" -m claude_runner run "{routine.path}"'


def cron_line(routine: Routine, python: str | None = None) -> str:
    if routine.daily_at:
        hh, mm = routine.daily_at.split(":")
        when = f"{int(mm)} {int(hh)} * * *"
    elif routine.weekly_at:
        day, hhmm = routine.weekly_at.split()
        hh, mm = hhmm.split(":")
        when = f"{int(mm)} {int(hh)} * * {CRON_DAYS[day]}"
    elif routine.every_minutes:
        if 60 % routine.every_minutes and routine.every_minutes < 60:
            raise ConfigError("no cron, every_minutes precisa dividir 60 (ex.: 5, 10, 15, 30)")
        when = (f"*/{routine.every_minutes} * * * *" if routine.every_minutes < 60
                else f"0 */{routine.every_minutes // 60} * * *")
    else:
        raise ConfigError("defina daily_at, weekly_at ou every_minutes na rotina")
    return f'{when} cd "{routine.cwd}" && {run_command(routine, python)} >> "{routine.state_dir}/cron.log" 2>&1'


def schtasks_command(routine: Routine, python: str | None = None) -> str:
    tr = run_command(routine, python).replace('"', '\\"')
    base = f'schtasks /Create /TN "claude-runner - {routine.name}" /TR "{tr}" /F'
    if routine.daily_at:
        return f"{base} /SC DAILY /ST {routine.daily_at}"
    if routine.weekly_at:
        day, hhmm = routine.weekly_at.split()
        return f"{base} /SC WEEKLY /D {day} /ST {hhmm}"
    if routine.every_minutes:
        return f"{base} /SC MINUTE /MO {routine.every_minutes}"
    raise ConfigError("defina daily_at, weekly_at ou every_minutes na rotina")
