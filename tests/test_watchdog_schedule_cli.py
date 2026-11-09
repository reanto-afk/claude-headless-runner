import io
import json
import urllib.request
from contextlib import redirect_stdout
from datetime import datetime

import pytest

from claude_runner import alert as alert_mod
from claude_runner.cli import main
from claude_runner.config import Alert, ConfigError, load_routine, parse_routine
from claude_runner.schedule import cron_line, schtasks_command
from claude_runner.state import StateDir
from claude_runner.watchdog import check

from .conftest import EXAMPLES


def at(hour: int) -> float:
    return datetime(2026, 11, 10, hour, 0).timestamp()


def test_vigia_avisa_uma_vez_e_lembra_depois_de_24h(make_routine, alerts):
    r = make_routine(expect_every_hours=24)
    t = at(9)
    assert check(r, t, alerts) is None  # 1ª vez: começa a contar
    assert check(r, t + 23 * 3600, alerts) is None
    msg = check(r, t + 25 * 3600, alerts)
    assert msg and "desde que o vigia começou" in msg and len(alerts.sent) == 1
    assert check(r, t + 26 * 3600, alerts) is None  # não repete
    assert check(r, t + 50 * 3600, alerts)  # lembra depois de 24h


def test_vigia_respeita_horario_comercial_e_sucesso_recente(make_routine, alerts):
    r = make_routine(expect_every_hours=1, business_hours="8-18")
    check(r, at(9) - 48 * 3600, alerts)
    assert check(r, at(22), alerts) is None  # fora do horário
    assert check(r, at(10), alerts)
    StateDir(r.state_dir).record({"kind": "ok", "finished_at": datetime.fromtimestamp(at(11)).isoformat()})
    assert check(r, at(11) + 1800, alerts) is None


def test_rotina_sem_janela_nao_e_vigiada(make_routine, alerts):
    assert check(make_routine(), at(10), alerts) is None


def test_agendamento(make_routine):
    assert cron_line(make_routine(daily_at="07:30"), "py").startswith("30 7 * * * ")
    assert cron_line(make_routine(weekly_at="FRI 16:00"), "py").startswith("0 16 * * 5 ")
    assert cron_line(make_routine(every_minutes=15), "py").startswith("*/15 * * * * ")
    assert cron_line(make_routine(every_minutes=120), "py").startswith("0 */2 * * * ")
    with pytest.raises(ConfigError):
        cron_line(make_routine(every_minutes=7), "py")
    cmd = schtasks_command(make_routine(weekly_at="FRI 16:00"), "py")
    assert '/TN "claude-runner - teste"' in cmd and cmd.endswith("/SC WEEKLY /D FRI /ST 16:00")
    assert schtasks_command(make_routine(every_minutes=30), "py").endswith("/SC MINUTE /MO 30")


@pytest.mark.parametrize("override", [
    {"name": "Com Espaço"}, {"prompt_file": "nao-existe.md"}, {"timeout_seconds": 0}, {"retry_on": ["inventado"]},
    {"business_hours": "18-8"}, {"daily_at": "7:30"}, {"daily_at": "07:30", "every_minutes": 30},
    {"weekly_at": "sexta 16:00"}, {"alert": {"format": "teams"}}, {"chave_errada": 1},
])
def test_rotina_invalida(make_routine, override):
    with pytest.raises(ConfigError):
        make_routine(**override)


def test_exemplos_sao_validos():
    for name in ("metrics-watchdog", "weekly-status"):
        r = load_routine(EXAMPLES / name / "routine.toml")
        assert r.name == name and r.prompt_file.is_file()


def test_alerta_sem_webhook_nao_quebra(capsys):
    err = alert_mod.send(Alert(), "[x] FALHOU", "motivo")
    assert "não configurado" in err and "motivo" in capsys.readouterr().err


@pytest.mark.parametrize("fmt,key", [("slack", "text"), ("discord", "content")])
def test_formato_do_webhook(monkeypatch, fmt, key):
    seen = {}

    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        return Resp()
    monkeypatch.setenv("HOOK_URL", "https://example.invalid/hook")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert alert_mod.send(Alert(webhook_env="HOOK_URL", format=fmt), "t", "b") is None
    assert seen["body"] == {key: "t\nb"}


def test_cli_run_status_history(make_routine, monkeypatch, tmp_path):
    from claude_runner import claude as claude_mod
    from .conftest import FAKE
    monkeypatch.setattr(claude_mod, "resolve_claude", lambda explicit=None: FAKE)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    (tmp_path / "routine.toml").write_text('name = "teste"\nprompt_file = "prompt.md"\n', encoding="utf-8")
    make_routine()  # cria o prompt.md
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert main(["run", str(tmp_path / "routine.toml")]) == 0
        assert main(["status", str(tmp_path)]) == 0
        assert main(["history", str(tmp_path / "routine.toml")]) == 0
        assert main(["run", "--dry-run", str(tmp_path / "routine.toml")]) == 0
        assert main(["schedule", str(EXAMPLES / "metrics-watchdog" / "routine.toml")]) == 0
    out = buf.getvalue()
    assert "teste: OK" in out and "RUN_OK" in out and "claude -p --output-format json" in out
    assert "/SC DAILY /ST 07:30" in out


def test_cli_erro_de_config_avisa(tmp_path, capsys):
    (tmp_path / "routine.toml").write_text('name = "x"\n', encoding="utf-8")
    assert main(["run", str(tmp_path / "routine.toml")]) == 2
    err = capsys.readouterr().err
    assert "prompt_file obrigatório" in err and "ALERTA" in err
