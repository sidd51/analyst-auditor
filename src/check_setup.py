"""Step 1: confirm packages, configuration, and OpenRouter access."""

from __future__ import annotations

import os
import sys

import httpx

from src.config import load_settings


def current_model_prices(model_id: str) -> tuple[float, float] | None:
    """Return OpenRouter's current USD price per million tokens."""
    try:
        response = httpx.get(
            "https://openrouter.ai/api/v1/models",
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    model = next(
        (
            item
            for item in response.json().get("data", [])
            if item.get("id") == model_id
        ),
        None,
    )
    if not model:
        return None
    pricing = model.get("pricing") or {}
    try:
        return (
            float(pricing["prompt"]) * 1_000_000,
            float(pricing["completion"]) * 1_000_000,
        )
    except (KeyError, TypeError, ValueError):
        return None


def main() -> int:
    try:
        settings = load_settings()
    except RuntimeError as exc:
        print(f"FAIL: {exc}")
        return 1

    missing = []
    for name in (
        "langchain_openai",
        "langchain_core",
        "langchain_text_splitters",
        "tavily",
        "pydantic",
        "httpx",
        "trafilatura",
        "bs4",
        "lxml",
        "ddgs",
        "pypdf",
        "dotenv",
    ):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        print("FAIL: missing packages:", ", ".join(missing))
        print("Run: pip install -r requirements.txt")
        return 1

    key = settings.openrouter_api_key.get_secret_value()
    tavily_ready = settings.tavily_api_key is not None
    print("Packages: OK")
    print(f"OpenRouter key: {key[:8]}...{key[-4:]}")
    print(f"Model: {settings.openrouter_model}")
    print(f"Tavily key: {'configured' if tavily_ready else 'not configured'}")
    print(f"USD to INR: {settings.usd_inr_rate}")
    print(
        "Model prices per million tokens: "
        f"${settings.input_usd_per_million} input / "
        f"${settings.output_usd_per_million} output"
    )
    pricing_is_explicit = bool(
        os.getenv("INPUT_USD_PER_MILLION")
        and os.getenv("OUTPUT_USD_PER_MILLION")
    )
    if settings.openrouter_model != "openai/gpt-4o-mini" and not pricing_is_explicit:
        print(
            "WARNING: default prices are for openai/gpt-4o-mini. "
            "Set INPUT_USD_PER_MILLION and OUTPUT_USD_PER_MILLION "
            "for your selected model before paid evaluation."
        )
    print(
        "Context budget: "
        f"{settings.max_model_input_tokens} input / "
        f"{settings.max_model_output_tokens} output tokens"
    )

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
    print("OpenRouter accepted the key.")
    print(f"  usage so far: {data.get('usage')}")
    print(f"  credit limit: {data.get('limit')}")

    current_prices = current_model_prices(settings.openrouter_model)
    if current_prices:
        current_input, current_output = current_prices
        configured = (
            settings.input_usd_per_million,
            settings.output_usd_per_million,
        )
        print(
            "OpenRouter current model prices: "
            f"${current_input:g} input / ${current_output:g} output per million"
        )
        if configured != current_prices:
            print(
                "WARNING: configured token prices differ from OpenRouter. "
                "Update INPUT_USD_PER_MILLION and "
                "OUTPUT_USD_PER_MILLION before evaluation."
            )

    if not tavily_ready:
        print(
            "NOTE: Add TAVILY_API_KEY to .env before the search step. "
            "DDGS will remain the fallback."
        )
    print("Step 1 setup is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
