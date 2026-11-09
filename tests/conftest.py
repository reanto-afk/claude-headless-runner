import sys
from pathlib import Path

import pytest

from claude_runner.config import parse_routine

FAKE = [sys.executable, str(Path(__file__).with_name("fake_claude.py"))]
EXAMPLES = Path(__file__).parent.parent / "examples"


class Clock:
    def __init__(self, t: float = 1_800_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, hours: float) -> None:
        self.t += hours * 3600


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("CLAUDE_RUNNER_WEBHOOK", "CLAUDE_RUNNER_STATE", "CLAUDE_RUNNER_CLAUDE_BIN", "FAKE_CLAUDE_MODE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_routine(tmp_path):
    (tmp_path / "prompt.md").write_text("Confira as métricas.\nÚltima linha: RUN_OK", encoding="utf-8")

    def factory(**overrides):
        data = {"name": "teste", "prompt_file": "prompt.md", "timeout_seconds": 20, "max_attempts": 3,
                "backoff_seconds": [1, 2]}
        data.update(overrides)
        return parse_routine(data, tmp_path / "routine.toml")
    return factory


@pytest.fixture
def alerts():
    sent = []

    def notify(alert, title, body):
        sent.append((title, body))
        return None
    notify.sent = sent
    return notify
