"""CLI: run, watchdog, status, history, schedule, validate."""
from __future__ import annotations

import argparse
import shlex
import sys
import traceback

from . import __version__
from . import alert as alert_mod
from .claude import build_command
from .config import Alert, ConfigError, discover, load_routine
from .runner import run_routine
from .schedule import cron_line, schtasks_command
from .state import StateDir
from .watchdog import check_all


def cmd_run(args) -> int:
    routine = load_routine(args.routine)
    if args.dry_run:
        print(" ".join(shlex.quote(c) for c in build_command(routine, ["claude"])))
        print(f"cwd: {routine.cwd}\nprompt (stdin): {routine.prompt_file}\nestado: {routine.state_dir}")
        return 0
    run = run_routine(routine)
    status = "OK" if run["kind"] == "ok" else f"FALHOU ({run['kind']})"
    print(f"{routine.name}: {status} · {run['duration_s']}s · US$ {run['cost_usd']:.4f} · {run['message']}")
    if run["alert_error"]:
        print(f"aviso: {run['alert_error']}", file=sys.stderr)
    return 0 if run["kind"] == "ok" else 1


def cmd_watchdog(args) -> int:
    routines = [load_routine(p) for p in discover(args.paths)]
    alerts = check_all(routines)
    for name, msg in alerts:
        print(f"{name}: {msg}")
    if not alerts:
        print(f"{len(routines)} rotina(s) dentro da janela esperada")
    return 1 if alerts else 0


def cmd_status(args) -> int:
    print(f"{'rotina':24} {'último':12} {'quando':26} {'último sucesso':26} custo")
    for path in discover(args.paths):
        r = load_routine(path)
        last = StateDir(r.state_dir).read_last()
        run = last.get("last_run", {})
        print(f"{r.name:24} {run.get('kind', '-'):12} {run.get('finished_at', '-'):26} "
              f"{last.get('last_success_at', '-'):26} {run.get('cost_usd', '-')}")
    return 0


def cmd_history(args) -> int:
    r = load_routine(args.routine)
    for run in StateDir(r.state_dir).read_history(args.n):
        print(f"{run['finished_at']}  {run['kind']:11} {len(run['attempts'])}x  {run['duration_s']:>6}s  "
              f"US$ {run['cost_usd']:.4f}  {run['message']}")
    return 0


def cmd_schedule(args) -> int:
    r = load_routine(args.routine)
    print("# cron (Linux/macOS): crontab -e e cole a linha")
    try:
        print(cron_line(r))
    except ConfigError as exc:
        print(f"# {exc}")
    print("\n# Agendador de Tarefas do Windows (cmd ou PowerShell):")
    print(schtasks_command(r))
    print("\n# vigia (sugestão: a cada hora)")
    print(f'# claude-runner watchdog "{r.path.parent}"')
    return 0


def cmd_validate(args) -> int:
    for path in discover(args.paths):
        r = load_routine(path)
        print(f"OK: {r.name} · {r.path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="claude-runner", description="Rotinas claude -p que não falham em silêncio.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("run", help="executa uma rotina")
    s.add_argument("routine")
    s.add_argument("--dry-run", action="store_true", help="só mostra o comando")
    s.set_defaults(fn=cmd_run)
    for name, fn, hlp in (("watchdog", cmd_watchdog, "avisa rotinas sem sucesso na janela esperada"),
                          ("status", cmd_status, "última execução de cada rotina"),
                          ("validate", cmd_validate, "valida arquivos de rotina")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("paths", nargs="+", help="arquivos .toml ou pastas (procura routine.toml)")
        s.set_defaults(fn=fn)
    s = sub.add_parser("history", help="histórico de uma rotina")
    s.add_argument("routine")
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(fn=cmd_history)
    s = sub.add_parser("schedule", help="mostra como agendar (não registra nada)")
    s.add_argument("routine")
    s.set_defaults(fn=cmd_schedule)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as exc:
        print(f"erro de configuração: {exc}", file=sys.stderr)
        alert_mod.send(Alert(), "[claude-runner] configuração inválida", str(exc))
        return 2
    except Exception as exc:  # o próprio runner quebrou: avisa em vez de morrer calado
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        print(f"erro inesperado: {detail}", file=sys.stderr)
        alert_mod.send(Alert(), "[claude-runner] erro inesperado", detail)
        return 3
