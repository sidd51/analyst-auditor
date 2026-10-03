"""Offline tests for eval report tables built from JSONL traces."""

from pathlib import Path

from src.eval.questions import QUESTIONS, by_id
from src.eval.report import write_reports


def test_locked_set_includes_q09_and_two_reuse() -> None:
    assert [item.qid for item in QUESTIONS] == [
        "Q01",
        "Q02",
        "Q03",
        "Q04",
        "Q05",
        "Q06",
        "Q07",
        "Q08",
        "Q09",
    ]
    assert by_id("q04").reuse is True
    assert by_id("q06").reuse is True
    assert by_id("q07").reuse is False
    assert by_id("q08").reuse is True
    assert by_id("q09").plant_unsupported is True
    assert sum(1 for item in QUESTIONS if item.reuse) >= 2


def test_report_writer_fills_tables_from_traces(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "q01-analyst.jsonl").write_text(
        "\n".join(
            [
                '{"event":"analyst_result","claims":[{"claim_id":"C01","field":"name",'
                '"text":"Ajoy Chawla","quote":"appointed as Managing Director",'
                '"urls":["https://example.com/titan"]}]}',
                '{"event":"final_answer","complete":true,"accepted":[{"claim_id":"C01",'
                '"field":"name","text":"Ajoy Chawla",'
                '"urls":["https://example.com/titan"]}],"missing":[],"disputed":[]}',
                '{"event":"audit_report","verdicts":[{"claim_id":"C01","verdict":"SUPPORTED",'
                '"reason":"The claim states the repo rate was 5.25% after the June 2026 '
                'Monetary Policy Committee decision and chose to hold.",'
                '"source_notes":[{"url":"https://example.com/rbi"}]},'
                '{"verdict":"UNSUPPORTED"}]}',
                '{"event":"memory_write","recalled_facts":[],"skipped_queries":[]}',
                '{"event":"run_end","ok":true,"complete":true,"total_tokens":1000,'
                '"cost_inr":1.5,"cost_usd":0.02,"wall_seconds":12.2}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_reports(tmp_path)
    cost = (tmp_path / "reports" / "cost.md").read_text(encoding="utf-8")
    auditor = (tmp_path / "reports" / "auditor.md").read_text(encoding="utf-8")
    page = (tmp_path / "ui" / "eval.html").read_text(encoding="utf-8")
    assert page == (tmp_path / "ui" / "index.html").read_text(encoding="utf-8")
    assert "| Q01 |" in cost
    assert "1.5000" in cost
    assert "| Q02 | — |" in cost
    assert "| Q01 | 1 | 1 | 0 | 0 | 0 | 0 |" in auditor
    assert "Q01" in page
    assert "const DATA =" in page
    assert "Cross Check" in page
    assert "appointed as Managing Director" in page
    assert "example.com/titan" in page
    assert "chose to hold" in page
    assert "example.com/rbi" in page
    assert "cold_qid" in page
