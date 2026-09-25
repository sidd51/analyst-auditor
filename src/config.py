"""Load and validate all environment settings in one place."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseModel):
    """Typed settings shared by every later pipeline stage."""

    root: Path = ROOT
    openrouter_api_key: SecretStr
    openrouter_model: str
    tavily_api_key: SecretStr | None = None

    usd_inr_rate: float = Field(gt=0)
    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)

    max_model_input_tokens: int = Field(gt=0)
    max_model_output_tokens: int = Field(gt=0)

    search_results_per_query: int = 5
    page_timeout_seconds: float = 15.0
    max_download_bytes: int = 20_000_000
    fetch_workers: int = 5
    retrieval_chunk_size: int = 1_200
    retrieval_chunk_overlap: int = 200
    max_passages_per_source: int = 3
    max_selected_passages: int = 12
    reserved_non_evidence_tokens: int = 4_000
    # First fetch wave. Later waves add `page_wave_size` pages only if
    # required fields are still missing. The model never chooses these.
    initial_page_budget: int = 5
    page_wave_size: int = 4
    absolute_page_ceiling: int = 15

    @property
    def evidence_token_budget(self) -> int:
        """Leave room for instructions, requirements, memory, and schemas."""
        return max(
            1_000,
            self.max_model_input_tokens - self.reserved_non_evidence_tokens,
        )

    @field_validator("openrouter_api_key")
    @classmethod
    def validate_openrouter_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value().strip()
        if not key:
            raise ValueError("OPENROUTER_API_KEY is missing")
        if not key.startswith("sk-or-") and len(key) < 20:
            raise ValueError("OPENROUTER_API_KEY does not look valid")
        return SecretStr(key)

    @field_validator("openrouter_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("OPENROUTER_MODEL is missing")
        return model


def load_settings(*, require_tavily: bool = False) -> Settings:
    """Read `.env`, validate it, and return one settings object."""
    load_dotenv(ROOT / ".env")
    tavily_key = (os.getenv("TAVILY_API_KEY") or "").strip()

    try:
        settings = Settings(
            openrouter_api_key=SecretStr(
                (os.getenv("OPENROUTER_API_KEY") or "").strip()
            ),
            openrouter_model=(os.getenv("OPENROUTER_MODEL") or "").strip(),
            tavily_api_key=SecretStr(tavily_key) if tavily_key else None,
            usd_inr_rate=float(os.getenv("USD_INR_RATE") or "83.5"),
            input_usd_per_million=float(
                os.getenv("INPUT_USD_PER_MILLION") or "0.15"
            ),
            output_usd_per_million=float(
                os.getenv("OUTPUT_USD_PER_MILLION") or "0.60"
            ),
            max_model_input_tokens=int(
                os.getenv("MAX_MODEL_INPUT_TOKENS") or "12000"
            ),
            max_model_output_tokens=int(
                os.getenv("MAX_MODEL_OUTPUT_TOKENS") or "2000"
            ),
        )
    except (ValueError, ValidationError) as exc:
        raise RuntimeError(f"Invalid environment configuration: {exc}") from exc

    if require_tavily and settings.tavily_api_key is None:
        raise RuntimeError(
            "TAVILY_API_KEY is missing. Add a free Tavily key to .env."
        )
    return settings
