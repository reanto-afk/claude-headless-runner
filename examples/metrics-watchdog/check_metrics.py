"""Núcleo determinístico da rotina metrics-watchdog: confere, não escreve.

- data de referência = dia útil anterior a --today;
- cada métrica tem um dono: "routine" (a rotina pode preencher) ou "pipeline" (só avisar o dono);
- vazio, divergência acima da tolerância e texto diferente (comparado por hash, sem expor o conteúdo).

Saída: JSON no stdout. Código 0 = conferiu; 2 = não conseguiu conferir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent


def previous_business_day(today: date) -> date:
    day = today - timedelta(days=1)
    while day.weekday() >= 5:  # sábado e domingo
        day -= timedelta(days=1)
    return day


def text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).lower().encode("utf-8")).hexdigest()


def check(metrics: dict, truth: dict, ref: str) -> dict:
    report = {"reference_date": ref, "ok": [], "empty": [], "divergent": [], "text_divergent": [], "no_truth": []}
    day_truth = truth.get(ref, {})
    for name, spec in sorted(metrics.items()):
        value = spec.get("values", {}).get(ref)
        owner = spec.get("owner", "pipeline")
        if spec.get("type") == "text":
            expected = day_truth.get(f"{name}_sha256")
            if value is None:
                report["empty"].append({"metric": name, "owner": owner, "can_fill_with": None})
            elif expected is None:
                report["no_truth"].append(name)
            elif text_hash(value) != expected:
                report["text_divergent"].append({"metric": name, "owner": owner})
            else:
                report["ok"].append(name)
            continue
        expected = day_truth.get(name)
        if value is None:
            report["empty"].append({"metric": name, "owner": owner,
                                    "can_fill_with": expected if owner == "routine" else None})
        elif expected is None:
            report["no_truth"].append(name)
        else:
            diff_pct = 0.0 if expected == value else abs(value - expected) / max(abs(expected), 1) * 100
            if diff_pct > spec.get("tolerance_pct", 0):
                report["divergent"].append({"metric": name, "owner": owner, "value": value,
                                            "truth": expected, "diff_pct": round(diff_pct, 2)})
            else:
                report["ok"].append(name)
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--today", default=date.today().isoformat(), help="AAAA-MM-DD")
    p.add_argument("--metrics", default=str(HERE / "data" / "metrics.json"))
    p.add_argument("--truth", default=str(HERE / "data" / "source_of_truth.json"))
    args = p.parse_args(argv)
    try:
        ref = previous_business_day(date.fromisoformat(args.today)).isoformat()
        metrics = json.loads(Path(args.metrics).read_text(encoding="utf-8"))["metrics"]
        truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(check(metrics, truth, ref), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
