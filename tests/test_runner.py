import json
import os
import time

import pytest

from claude_runner.runner import run_routine
from claude_runner.state import StateDir

from .conftest import FAKE


def run(routine, monkeypatch, mode, alerts, **kw):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
    return run_routine(routine, FAKE, sleep=lambda s: None, notify=alerts, **kw)


def test_ok_grava_historico_e_ultimo_sucesso(make_routine, monkeypatch, alerts):
    r = make_routine()
    res = run(r, monkeypatch, "ok", alerts)
    assert res["kind"] == "ok" and len(res["attempts"]) == 1 and res["cost_usd"] == 0.0012
    assert alerts.sent == []  # sucesso sem notify_on_success não avisa
    last = StateDir(r.state_dir).read_last()
    assert last["last_success_at"] == res["finished_at"]


def test_prompt_vai_pelo_stdin_e_flags_certas(make_routine, monkeypatch, alerts):
    r = make_routine(model="haiku", allowed_tools=["Read", "Bash(python x.py:*)"], extra_args=["--setting-sources", "project"])
    res = run(r, monkeypatch, "echo", alerts)
    echoed = json.loads(res["attempts"][0]["result"].rsplit("\n", 1)[0])
    assert echoed["prompt"].startswith("Confira as métricas.")
    assert echoed["argv"] == ["-p", "--output-format", "json", "--model", "haiku", "--setting-sources", "project",
                              "--allowedTools", "Read", "Bash(python x.py:*)"]


@pytest.mark.parametrize("mode,kind,tries", [
    ("auth", "auth", 1), ("rate_limit", "rate_limit", 1), ("contract", "contract", 1),
    ("run_failed", "run_failed", 1), ("max_turns", "max_turns", 1),
    ("overloaded", "overloaded", 3), ("crash", "crash", 3),
])
def test_so_repete_o_que_e_transitorio(make_routine, monkeypatch, alerts, mode, kind, tries):
    res = run(make_routine(), monkeypatch, mode, alerts)
    assert res["kind"] == kind and len(res["attempts"]) == tries
    assert len(alerts.sent) == 1 and "FALHOU" in alerts.sent[0][0]


def test_mensagens_em_portugues_simples(make_routine, monkeypatch, alerts):
    assert "/login" in run(make_routine(), monkeypatch, "auth", alerts)["message"]
    assert "data/metrics.json não existe" in run(make_routine(), monkeypatch, "run_failed", alerts)["message"]
    assert "após 3 tentativas" in run(make_routine(), monkeypatch, "overloaded", alerts)["message"]


def test_instavel_e_depois_ok(make_routine, monkeypatch, alerts, tmp_path):
    monkeypatch.setenv("FAKE_CLAUDE_COUNTER", str(tmp_path / "counter"))
    waits = []
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "flaky")
    res = run_routine(make_routine(), FAKE, sleep=waits.append, notify=alerts)
    assert res["kind"] == "ok" and [a["kind"] for a in res["attempts"]] == ["overloaded", "overloaded", "ok"]
    assert waits == [1, 2] and alerts.sent == []


def test_timeout_mata_o_processo(make_routine, monkeypatch, alerts):
    r = make_routine(timeout_seconds=2, max_attempts=1)
    t0 = time.monotonic()
    res = run(r, monkeypatch, "timeout", alerts)
    assert res["kind"] == "timeout" and time.monotonic() - t0 < 15
    assert "2s" in res["message"]


def test_notify_on_success_manda_o_texto_sem_a_linha_de_contrato(make_routine, monkeypatch, alerts):
    r = make_routine(alert={"notify_on_success": True})
    run(r, monkeypatch, "ok", alerts)
    title, body = alerts.sent[0]
    assert title == "[teste] ok" and body == "Tudo conferido.\nNada divergente."


def test_claude_inexistente_vira_alerta(make_routine, monkeypatch, alerts):
    monkeypatch.setenv("CLAUDE_RUNNER_CLAUDE_BIN", "claude-que-nao-existe-123")
    res = run_routine(make_routine(), None, sleep=lambda s: None, notify=alerts)
    assert res["kind"] == "setup" and "não encontrado" in res["message"] and alerts.sent


def test_execucao_sobreposta_e_pulada(make_routine, monkeypatch, alerts):
    r = make_routine()
    state = StateDir(r.state_dir)
    with state.single_instance(stale_after=999):
        res = run(r, monkeypatch, "ok", alerts)
    assert res["kind"] == "overlap" and alerts.sent


def test_trava_velha_de_processo_morto_e_ignorada(make_routine, monkeypatch, alerts):
    r = make_routine()
    r.state_dir.mkdir(parents=True)
    lock = r.state_dir / "run.lock"
    lock.write_text("99999")
    old = time.time() - 10 * 3600
    os.utime(lock, (old, old))
    res = run(r, monkeypatch, "ok", alerts)
    assert res["kind"] == "ok"


def test_historico_tem_limite(make_routine, monkeypatch, alerts):
    import claude_runner.state as st
    monkeypatch.setattr(st, "MAX_HISTORY", 3)
    r = make_routine()
    for _ in range(5):
        run(r, monkeypatch, "ok", alerts)
    assert len(StateDir(r.state_dir).read_history(100)) == 3
