"""Estado por rotina: histórico JSONL, última execução e trava de instância única."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

MAX_HISTORY = 1000


class StateDir:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.history = self.path / "runs.jsonl"
        self.last = self.path / "last.json"
        self.watchdog = self.path / "watchdog.json"
        self._lock = self.path / "run.lock"

    def _write_json(self, target: Path, data: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)

    def _read_json(self, target: Path) -> dict:
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    @contextmanager
    def single_instance(self, stale_after: float):
        """Garante uma execução por vez; trava mais velha que `stale_after` é de processo morto.

        Usa sempre o relógio real: a idade vem do mtime do arquivo.
        """
        self.path.mkdir(parents=True, exist_ok=True)
        acquired = False
        try:
            try:
                fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = time.time() - self._lock.stat().st_mtime
                if age <= stale_after:
                    yield False
                    return
                self._lock.unlink(missing_ok=True)
                fd = os.open(self._lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            acquired = True
            yield True
        finally:
            if acquired:
                self._lock.unlink(missing_ok=True)

    def record(self, run: dict) -> None:
        self.path.mkdir(parents=True, exist_ok=True)
        lines = []
        if self.history.exists():
            lines = self.history.read_text(encoding="utf-8").splitlines()[-(MAX_HISTORY - 1):]
        lines.append(json.dumps(run, ensure_ascii=False))
        tmp = self.history.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.history)
        last = self.read_last()
        last["last_run"] = run
        if run["kind"] == "ok":
            last["last_success_at"] = run["finished_at"]
        self._write_json(self.last, last)

    def read_last(self) -> dict:
        return self._read_json(self.last)

    def read_history(self, n: int = 20) -> list[dict]:
        if not self.history.exists():
            return []
        return [json.loads(ln) for ln in self.history.read_text(encoding="utf-8").splitlines()[-n:] if ln]

    def read_watchdog(self) -> dict:
        return self._read_json(self.watchdog)

    def write_watchdog(self, data: dict) -> None:
        self._write_json(self.watchdog, data)
