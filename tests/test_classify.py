import json

import pytest

from claude_runner.claude import check_contract, classify


@pytest.mark.parametrize("text,kind,detail", [
    ("resumo\nRUN_OK", "ok", ""),
    ("resumo\n`RUN_OK`\n", "ok", ""),
    ("**RUN_OK**", "ok", ""),
    ("x\nRUN_FAILED: script quebrou", "run_failed", "script quebrou"),
    ("RUN_FAILED", "run_failed", "sem motivo informado"),
    ("RUN_OK\ndepois disso mais texto", "contract", "última linha: 'depois disso mais texto'"),
    ("", "contract", "resposta vazia"),
])
def test_contrato(text, kind, detail):
    assert check_contract(text) == (kind, detail)


def out(**kw):
    base = {"type": "result", "subtype": "success", "is_error": False, "result": "RUN_OK",
            "session_id": "s", "total_cost_usd": 0.01, "api_error_status": None}
    base.update(kw)
    return json.dumps(base)


@pytest.mark.parametrize("stdout,stderr,kind", [
    (out(), "", "ok"),
    (out(is_error=True, api_error_status=401, result="Invalid API key · Please run /login"), "", "auth"),
    (out(is_error=True, api_error_status=429, result="usage limit reached"), "", "rate_limit"),
    (out(is_error=True, api_error_status=529, result="Overloaded"), "", "overloaded"),
    (out(is_error=True, api_error_status=500, result="erro"), "", "overloaded"),
    (out(is_error=True, subtype="error_max_turns", result=""), "", "max_turns"),
    ("", "Please run /login", "auth"),
    ("", "Error: boom", "crash"),
    ("lixo não json", "", "crash"),
    ("aviso qualquer\n" + out(), "", "ok"),  # JSON na última linha
])
def test_classificacao(stdout, stderr, kind):
    assert classify(1, stdout, stderr).kind == kind


def test_guarda_sessao_e_custo():
    a = classify(0, out(result="ok\nRUN_OK"), "")
    assert a.session_id == "s" and a.cost_usd == 0.01 and a.result.endswith("RUN_OK")
