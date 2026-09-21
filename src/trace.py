"""Append-only JSONL traces. Reviewers want the full story, not the final answer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Tracer:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def event(self, kind: str, **payload: Any) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": kind,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
