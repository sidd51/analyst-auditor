"""Save audited facts. Only 'supported' may be reused later."""

import json
from pathlib import Path

from src.config import load_settings


def memory_path() -> Path:
    return load_settings().root / "data" / "memory.json"


def load_memory() -> dict:
    path = memory_path()
    if not path.exists():
        return {"entities": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def remembered_texts() -> list[str]:
    mem = load_memory()
    texts = []
    for entity in mem.get("entities", {}).values():
        for fact in entity.get("facts", []):
            texts.append(fact["text"])
    return texts


def write_supported(entity: str, reports: list[dict]) -> Path:
    mem = load_memory()
    bucket = mem["entities"].setdefault(entity, {"facts": []})
    existing = {f["text"] for f in bucket["facts"]}

    for row in reports:
        if row.get("verdict") != "supported":
            continue
        claim = row["claim"]
        text = claim.get("text") or ""
        if not text or text in existing:
            continue
        bucket["facts"].append(
            {
                "text": text,
                "url": claim.get("url") or "",
                "verdict": "supported",
            }
        )
        existing.add(text)

    path = memory_path()
    path.write_text(json.dumps(mem, indent=2), encoding="utf-8")
    return path