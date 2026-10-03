"""Build cost and auditor tables from committed Q1–Q9 JSONL traces."""

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


def last_purpose(events: list[dict], purpose: str) -> dict | None:
    for row in reversed(events):
        if row.get("event") == "llm_response" and row.get("purpose") == purpose:
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
    (reports / "cost.md").write_text(_cost_markdown(rows, root), encoding="utf-8")
    (reports / "auditor.md").write_text(_auditor_markdown(rows), encoding="utf-8")
    write_eval_page(root, rows)


def _unique_urls(values) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def compact_trace(events: list[dict]) -> dict:
    spec = (last_purpose(events, "specify_question") or {}).get("output") or {}
    recall = last_event(events, "memory_recall") or {}
    packet = last_event(events, "evidence_packet") or {}
    analyst = last_event(events, "analyst_result") or {}
    planted = last_event(events, "planted_claim")
    cross = last_event(events, "cross_check_report") or {}
    audit = last_event(events, "audit_report") or {}
    final = last_event(events, "final_answer") or {}
    start = last_event(events, "run_start") or {}

    queries = [
        {"query": row.get("query") or "", "targets": row.get("targets") or []}
        for row in events
        if row.get("event") == "planned_search" and row.get("query")
    ][:4]

    fetches: list[dict] = []
    seen: set[str] = set()
    for row in events:
        if row.get("event") != "tool_result" or row.get("tool") != "fetch_page":
            continue
        url = str(row.get("final_url") or row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        fetches.append(
            {
                "url": url,
                "ok": bool(row.get("ok")),
                "title": (row.get("title") or "")[:80],
            }
        )
        if len(fetches) >= 6:
            break

    return {
        "question": start.get("question") or "",
        "required_fields": spec.get("required_fields") or [],
        "entities": spec.get("entities") or [],
        "memory_verify": bool(recall.get("memory_verify")),
        "known_fields": recall.get("known_fields") or [],
        "stored_urls": (recall.get("stored_urls") or [])[:3],
        "queries": queries,
        "fetches": fetches,
        "pages_used": packet.get("pages_used"),
        "passages_selected": packet.get("passages_selected"),
        "claims": [
            {
                "claim_id": item.get("claim_id") or "",
                "field": item.get("field") or "",
                "text": item.get("text") or "",
                "quote": item.get("quote") or "",
                "urls": [url for url in (item.get("urls") or []) if url][:3],
            }
            for item in (analyst.get("claims") or [])[:6]
        ],
        "unanswered": [
            {
                "field": item.get("field") or "",
                "reason": item.get("reason") or "",
            }
            for item in (analyst.get("unanswered") or [])[:4]
        ],
        "planted": (
            {
                "claim_id": planted.get("claim_id"),
                "text": planted.get("text"),
                "quote": planted.get("quote") or "",
                "urls": [url for url in (planted.get("urls") or []) if url][:3],
            }
            if planted
            else None
        ),
        "cross_check_skipped": bool(cross.get("skipped")),
        "cross_check": [
            {
                "claim_id": item.get("claim_id") or "",
                "status": item.get("status") or "",
                "reason": item.get("reason") or "",
                "independent_url": item.get("independent_url") or "",
                "evidence_origin": item.get("evidence_origin") or "",
            }
            for item in (cross.get("verdicts") or [])
        ],
        "auditor": [
            {
                "claim_id": item.get("claim_id") or "",
                "verdict": item.get("verdict") or "",
                "reason": item.get("reason") or "",
                "urls": _unique_urls(
                    note.get("url") for note in (item.get("source_notes") or [])
                ),
            }
            for item in (audit.get("verdicts") or [])
        ],
        "accepted": [
            {
                "field": item.get("field") or "",
                "text": item.get("text") or "",
                "sources": item.get("sources") or [],
                "urls": _unique_urls(item.get("urls") or []),
            }
            for item in (final.get("accepted") or [])
        ],
        "missing": [
            {
                "field": item.get("field") or "",
                "reason": item.get("reason") or "",
            }
            for item in (final.get("missing") or [])
        ],
        "disputed": [
            {
                "field": item.get("field") or "",
                "claim_id": item.get("claim_id") or "",
                "reason": item.get("reason") or "",
                "urls": _unique_urls(item.get("urls") or []),
            }
            for item in (final.get("disputed") or [])
        ],
        "complete": bool(final.get("complete")),
    }


def naive_snapshot(root: Path) -> dict:
    events = load_events(root / "logs" / "q01-naive.jsonl")
    ended = last_event(events, "run_end") or {}
    answer = last_event(events, "naive_answer") or {}
    return {
        "present": bool(events),
        "answer": answer.get("answer") or "",
        "tokens": int(ended.get("total_tokens") or 0),
        "cost_inr": float(ended.get("cost_inr") or 0),
        "wall_seconds": float(ended.get("wall_seconds") or 0),
    }


def _pct_drop(before: float, after: float) -> int | None:
    if not before:
        return None
    return round((1 - after / before) * 100)


def _memory_verify(root: Path, qid: str) -> bool:
    events = load_events(root / "logs" / f"{qid.lower()}-analyst.jsonl")
    return bool((last_event(events, "memory_recall") or {}).get("memory_verify"))


def cold_warm_pair(root: Path, rows: list[dict]) -> tuple[dict, dict, str, str]:
    """Use a full-search question vs its memory-verify twin, not a re-run of Q01."""
    by_qid = {row["qid"]: row for row in rows}
    for cold_id, warm_id in (("Q01", "Q06"), ("Q05", "Q08")):
        cold = by_qid.get(cold_id) or {}
        warm = by_qid.get(warm_id) or {}
        if not cold.get("present") or not warm.get("present"):
            continue
        if not _memory_verify(root, cold_id) and _memory_verify(root, warm_id):
            return cold, warm, cold_id, warm_id
    return by_qid.get("Q01") or {}, by_qid.get("Q06") or {}, "Q01", "Q06"


def eval_page_data(root: Path, rows: list[dict]) -> dict:
    cold, warm, cold_id, warm_id = cold_warm_pair(root, rows)
    questions = {item.qid: item for item in QUESTIONS}
    detail = []
    for row in rows:
        item = questions[row["qid"]]
        events = load_events(root / "logs" / f"{row['qid'].lower()}-analyst.jsonl")
        detail.append(
            {
                **row,
                "question": item.question,
                "reuse": item.reuse,
                "plant_unsupported": item.plant_unsupported,
                "trace": compact_trace(events) if events else {},
            }
        )
    return {
        "questions": detail,
        "naive": naive_snapshot(root),
        "metrics": {
            "token_drop_pct": _pct_drop(
                float(cold.get("tokens") or 0), float(warm.get("tokens") or 0)
            ),
            "cost_drop_pct": _pct_drop(
                float(cold.get("cost_inr") or 0), float(warm.get("cost_inr") or 0)
            ),
            "time_drop_pct": _pct_drop(
                float(cold.get("wall_seconds") or 0),
                float(warm.get("wall_seconds") or 0),
            ),
            "cold_qid": cold_id,
            "warm_qid": warm_id,
            "q01_tokens": int(cold.get("tokens") or 0),
            "q06_tokens": int(warm.get("tokens") or 0),
            "q01_cost_inr": float(cold.get("cost_inr") or 0),
            "q06_cost_inr": float(warm.get("cost_inr") or 0),
            "q01_seconds": float(cold.get("wall_seconds") or 0),
            "q06_seconds": float(warm.get("wall_seconds") or 0),
        },
    }


def write_eval_page(root: Path, rows: list[dict]) -> Path:
    payload = eval_page_data(root, rows)
    template = Path(__file__).with_name("eval_page.html").read_text(encoding="utf-8")
    html = template.replace("/*__EVAL_DATA__*/", json.dumps(payload, ensure_ascii=True))
    out = root / "ui" / "eval.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    (out.parent / "index.html").write_text(html, encoding="utf-8")
    return out


def _cost_markdown(rows: list[dict], root: Path | None = None) -> str:
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
    if root is not None:
        cold, warm, cold_id, warm_id = cold_warm_pair(root, rows)
        if cold.get("present") and warm.get("present") and cold.get("cost_inr"):
            drop = _pct_drop(float(cold["cost_inr"]), float(warm["cost_inr"]))
            extra = f" (−{drop}%)." if drop is not None and drop >= 0 else "."
            if drop is not None and drop < 0:
                extra = f" (+{abs(drop)}%)."
            lines.extend(
                [
                    "",
                    f"Memory pair: cold {cold_id} ₹{cold['cost_inr']:.4f} → "
                    f"verify {warm_id} ₹{warm['cost_inr']:.4f}{extra}",
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
    print(f"Wrote {settings.root / 'ui' / 'eval.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
