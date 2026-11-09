"""`claude -p --output-format json` falso para testes offline (sem tokens).

FAKE_CLAUDE_MODE: ok | run_failed | contract | auth | rate_limit | overloaded | max_turns | timeout | crash | flaky | echo
FAKE_CLAUDE_COUNTER: arquivo para o modo flaky (falha 'overloaded' até a 3ª chamada).
"""
import json
import os
import sys
import time
from pathlib import Path


def result(text, is_error=False, subtype="success", status=None):
    print(json.dumps({"type": "result", "subtype": subtype, "is_error": is_error, "result": text,
                      "session_id": "00000000-0000-0000-0000-000000000001", "total_cost_usd": 0.0012,
                      "api_error_status": status, "num_turns": 1}))


def main():
    mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
    prompt = sys.stdin.buffer.read().decode("utf-8")
    if mode == "flaky":
        counter = Path(os.environ["FAKE_CLAUDE_COUNTER"])
        n = int(counter.read_text()) + 1 if counter.exists() else 1
        counter.write_text(str(n))
        mode = "overloaded" if n < 3 else "ok"
    if mode == "ok":
        result("Tudo conferido.\nNada divergente.\nRUN_OK")
    elif mode == "run_failed":
        result("O script não achou o arquivo.\nRUN_FAILED: data/metrics.json não existe")
    elif mode == "contract":
        result("Terminei a conferência, tudo certo!")
    elif mode == "auth":
        result("Invalid API key · Please run /login", True, "success", 401)
    elif mode == "rate_limit":
        result("Claude AI usage limit reached", True, "success", 429)
    elif mode == "overloaded":
        result("Overloaded", True, "success", 529)
    elif mode == "max_turns":
        result("", True, "error_max_turns")
    elif mode == "timeout":
        time.sleep(30)
    elif mode == "crash":
        print("Error: something exploded", file=sys.stderr)
        sys.exit(1)
    elif mode == "echo":
        result(json.dumps({"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd()}, ensure_ascii=False) + "\nRUN_OK")


if __name__ == "__main__":
    main()
