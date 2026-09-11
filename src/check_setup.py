"""Step 1: confirm YOUR local init works before we write any agent code."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> int:
    key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    model = (os.getenv("OPENROUTER_MODEL") or "").strip()
    usd_inr = (os.getenv("USD_INR_RATE") or "").strip()

    if not key:
        print("FAIL: OPENROUTER_API_KEY is missing.")
        print("Do this: copy .env.example to .env, paste your key, run this again.")
        return 1
    if key.startswith("sk-or-") is False and len(key) < 20:
        print("FAIL: OPENROUTER_API_KEY does not look like an OpenRouter key.")
        print("OpenRouter keys usually start with sk-or-")
        return 1
    if not model:
        print("FAIL: OPENROUTER_MODEL is empty. Set it in .env")
        return 1

    print(f"Key loaded: {key[:8]}...{key[-4:]}")
    print(f"Model you chose: {model}")
    print(f"USD_INR_RATE: {usd_inr or '(missing)'}")

    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        print(f"FAIL: could not reach OpenRouter: {exc}")
        return 1

    if response.status_code == 401:
        print("FAIL: OpenRouter rejected the key (401). Paste a fresh key into .env")
        return 1
    if response.status_code >= 400:
        print(f"FAIL: OpenRouter returned {response.status_code}: {response.text[:300]}")
        return 1

    data = response.json().get("data") or {}
    limit = data.get("limit")
    usage = data.get("usage")
    print("OpenRouter accepted the key.")
    print(f"  usage so far: {usage}")
    print(f"  credit limit: {limit}")
    print("Step 1 init is done. Tell me 'step 1 done' and we start Step 2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
