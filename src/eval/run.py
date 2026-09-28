"""Run the locked Q1–Q9 set. Memory stays warm unless --fresh is set."""

from __future__ import annotations

import argparse
import sys
import time

from src.analyze import _print_run, _trace_run, run_question
from src.config import load_settings
from src.eval.questions import QUESTIONS, by_id
from src.eval.report import write_reports
from src.llm import OpenRouterLLM
from src.memory import EntityMemory
from src.trace import JsonlTracer


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Q1–Q9 with shared entity memory. This is a paid live run."
    )
    parser.add_argument(
        "--only",
        nargs="+",
        default=[],
        help="Run these IDs only, for example Q01 Q04.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Delete data/memory.json before Q01 so the eval starts empty.",
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=20,
        help="Seconds to wait between questions so OpenRouter in-flight budget clears.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    selected = [by_id(item) for item in args.only] if args.only else list(QUESTIONS)
    memory = EntityMemory.load(settings)
    if args.fresh and memory.path.exists():
        memory.path.unlink()
        memory = EntityMemory.load(settings)

    llm = OpenRouterLLM(settings, JsonlTracer(settings.root / "logs" / "eval-llm.jsonl"))
    failed = 0
    for index, item in enumerate(selected):
        if index and args.pause > 0:
            print(f"Pausing {args.pause}s before {item.qid} (OpenRouter in-flight budget).")
            time.sleep(args.pause)
        trace_path = settings.root / "logs" / f"{item.qid.lower()}-analyst.jsonl"
        tracer = JsonlTracer(trace_path, reset=True)
        llm.tracer = tracer
        tracer.event(
            "run_start",
            step="eval",
            qid=item.qid,
            question=item.question,
            reuse=item.reuse,
        )
        print(f"\n===== {item.qid} =====")
        try:
            run = run_question(
                item.question,
                list(item.notes),
                settings,
                tracer,
                llm,
                memory,
                plant_unsupported=item.plant_unsupported,
            )
        except Exception as exc:
            tracer.event("run_end", ok=False, qid=item.qid, error=str(exc))
            print(f"FAIL {item.qid}: {type(exc).__name__}: {exc}")
            print(f"Trace: {trace_path}")
            failed += 1
            continue
        _trace_run(tracer, run, memory)
        _print_run(run, memory, trace_path)

    write_reports(settings.root)
    print(f"\nReports: {settings.root / 'reports'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
