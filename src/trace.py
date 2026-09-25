"""Write an inspectable, append-only JSONL trace for each run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JsonlTracer:
    """Append one timestamped JSON object per event.

    JSONL is intentionally simple: reviewers can read it in a text editor, and
    a failed run still keeps every event written before the failure.
    """

    def __init__(self, path: Path, *, reset: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            self.path.write_text("", encoding="utf-8")

    def event(self, event_type: str, **payload: Any) -> None:
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
