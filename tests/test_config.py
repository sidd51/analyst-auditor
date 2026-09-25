"""Small tests for the Step 1 configuration contract."""

import pytest
from pydantic import SecretStr, ValidationError

from src.config import Settings


def valid_settings(**overrides: object) -> Settings:
    values = {
        "openrouter_api_key": SecretStr("sk-or-v1-test-key-long-enough"),
        "openrouter_model": "openai/gpt-4o-mini",
        "usd_inr_rate": 83.5,
        "input_usd_per_million": 0.15,
        "output_usd_per_million": 0.60,
        "max_model_input_tokens": 12_000,
        "max_model_output_tokens": 2_000,
    }
    values.update(overrides)
    return Settings(**values)


def test_page_budget_uses_waves_not_question_complexity() -> None:
    settings = valid_settings()

    assert settings.initial_page_budget == 5
    assert settings.page_wave_size == 4
    assert settings.absolute_page_ceiling == 15


def test_empty_openrouter_key_is_rejected() -> None:
    with pytest.raises(ValidationError):
        valid_settings(openrouter_api_key=SecretStr(""))


def test_tavily_is_optional_until_search_step() -> None:
    settings = valid_settings()

    assert settings.tavily_api_key is None
