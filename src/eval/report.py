"""Build cost and auditor tables from committed Q1–Q8 JSONL traces."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from src.config import load_settings
from src.eval.questions import QUESTIONS


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def last_event(events: list[dict], name: str) -> dict | None:
    for row in reversed(events):
        if row.get("event") == name:
            return row
    return None


def question_row(root: Path, qid: str) -> dict:
    events = load_events(root / "logs" / f"{qid.lower()}-analyst.jsonl")
    ended = last_event(events, "run_end") or {}
    final = last_event(events, "final_answer") or {}
    memory = last_event(events, "memory_write") or {}
    audit = last_event(events, "audit_report") or {}
    verdicts = audit.get("verdicts") or []
    counts = Counter(item.get("verdict") for item in verdicts)
    return {
        "qid": qid,
        "ok": bool(ended.get("ok")),
        "complete": bool(final.get("complete")),
        "accepted": len(final.get("accepted") or []),
        "missing": len(final.get("missing") or []),
        "disputed": len(final.get("disputed") or []),
        "tokens": int(ended.get("total_tokens") or 0),
        "cost_inr": float(ended.get("cost_inr") or 0),
        "cost_usd": float(ended.get("cost_usd") or 0),
        "wall_seconds": float(ended.get("wall_seconds") or 0),
        "recalled": len(memory.get("recalled_facts") or []),
        "skipped_queries": len(memory.get("skipped_queries") or []),
        "supported": counts.get("SUPPORTED", 0),
        "unsupported": counts.get("UNSUPPORTED", 0),
        "contradicted": counts.get("CONTRADICTED", 0),
        "uncited": counts.get("UNCITED", 0),
        "present": bool(events),
    }


def write_reports(root: Path) -> None:
    rows = [question_row(root, item.qid) for item in QUESTIONS]
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "cost.md").write_text(_cost_markdown(rows), encoding="utf-8")
    (reports / "auditor.md").write_text(_auditor_markdown(rows), encoding="utf-8")


def _cost_markdown(rows: list[dict]) -> str:
    lines = [
        "# Cost by question",
        "",
        "Numbers come from `logs/qNN-analyst.jsonl` `run_end` events.",
        "Memory is shared across the run. Caching a previous final answer does not happen.",
        "",
        "| Q | ok | complete | tokens | ₹ | USD | seconds | memory facts used | queries skipped |",
        "|---|----|----------|--------|---|-----|---------|-------------------|-----------------|",
    ]
    for row in rows:
        if not row["present"]:
            lines.append(f"| {row['qid']} | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            "| {qid} | {ok} | {complete} | {tokens} | {cost_inr:.4f} | "
            "{cost_usd:.6f} | {wall_seconds:.1f} | {recalled} | {skipped_queries} |".format(
                **row
            )
        )
    present = [row for row in rows if row["present"] and row["ok"]]
    if present:
        first = present[0]
        last = present[-1]
        drop = (
            (1 - last["cost_inr"] / first["cost_inr"]) * 100
            if first["cost_inr"]
            else 0
        )
        lines.extend(
            [
                "",
                f"First scored question: {first['qid']} ₹{first['cost_inr']:.4f}.",
                f"Last scored question: {last['qid']} ₹{last['cost_inr']:.4f} "
                f"({drop:.0f}% vs first).",
            ]
        )
    return "\n".join(lines) + "\n"


def _auditor_markdown(rows: list[dict]) -> str:
    lines = [
        "# Auditor catches",
        "",
        "Counts are from the `audit_report` event in each question trace.",
        "A rubber-stamp run would be all SUPPORTED and no missing/disputed rows.",
        "",
        "| Q | SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCITED | missing | disputed |",
        "|---|-----------|-------------|--------------|---------|---------|----------|",
    ]
    for row in rows:
        if not row["present"]:
            lines.append(f"| {row['qid']} | — | — | — | — | — | — |")
            continue
        lines.append(
            "| {qid} | {supported} | {unsupported} | {contradicted} | "
            "{uncited} | {missing} | {disputed} |".format(**row)
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    del argv
    settings = load_settings()
    write_reports(settings.root)
    print(f"Wrote {settings.root / 'reports' / 'cost.md'}")
    print(f"Wrote {settings.root / 'reports' / 'auditor.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
