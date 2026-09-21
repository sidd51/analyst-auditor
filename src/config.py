"""Load settings from .env. One place so the rest of the code does not scatter os.getenv."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path
    api_key: str
    model: str
    usd_inr_rate: float
    brave_api_key: str | None


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    model = (os.getenv("OPENROUTER_MODEL") or "").strip()
    rate_raw = (os.getenv("USD_INR_RATE") or "83.5").strip()
    brave = (os.getenv("BRAVE_API_KEY") or "").strip() or None
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is missing. Copy .env.example to .env.")
    if not model:
        raise RuntimeError("OPENROUTER_MODEL is empty. Set it in .env.")
    return Settings(
        root=ROOT,
        api_key=key,
        model=model,
        usd_inr_rate=float(rate_raw),
        brave_api_key=brave,
    )
