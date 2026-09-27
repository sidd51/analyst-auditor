"""Small LangChain wrapper used by both future agents."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Generic, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from src.config import Settings
from src.cost import CostRecord, calculate_cost
from src.trace import JsonlTracer

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass(frozen=True)
class StructuredResult(Generic[SchemaT]):
    """Validated model output plus the usage data for that exact call."""

    value: SchemaT
    cost: CostRecord
    generation_id: str


class OpenRouterLLM:
    """Call OpenRouter through LangChain and always request a Pydantic schema."""

    def __init__(self, settings: Settings, tracer: JsonlTracer) -> None:
        self.settings = settings
        self.tracer = tracer

        # LangChain handles OpenRouter request/response details. Our own Python
        # pipeline will still decide when calls happen and what they may do.
        # We use LangChain's mature OpenAI-compatible adapter with OpenRouter's
        # documented base URL. The beta ChatOpenRouter transport repeatedly
        # timed out in testing while the same direct request took 1.43 seconds.
        self._max_output_tokens = settings.max_model_output_tokens
        self.model = self._make_model()

    def _make_model(self) -> ChatOpenAI:
        return ChatOpenAI(
            model=self.settings.openrouter_model,
            api_key=self.settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/sidd51/analyst-auditor",
                "X-Title": "Analyst-Auditor",
            },
            temperature=0,
            max_tokens=self._max_output_tokens,
            max_retries=0,
            timeout=45,
        )

    def complete_structured(
        self,
        *,
        purpose: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[SchemaT],
    ) -> StructuredResult[SchemaT]:
        """Make one traced call and reject output that violates `schema`."""
        self.tracer.event(
            "llm_request",
            purpose=purpose,
            model=self.settings.openrouter_model,
            schema=schema.__name__,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

        try:
            response = self._invoke_structured(
                schema, system_prompt, user_prompt
            )
        except Exception as exc:
            self.tracer.event(
                "llm_error",
                purpose=purpose,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise

        parsed = response.get("parsed")
        parsing_error = response.get("parsing_error")
        raw = response.get("raw")
        if parsing_error or not isinstance(parsed, schema) or raw is None:
            self.tracer.event(
                "llm_error",
                purpose=purpose,
                error_type="StructuredOutputError",
                error=str(parsing_error or "missing parsed or raw response"),
            )
            raise RuntimeError(
                f"OpenRouter returned invalid structured output for {purpose}"
            )

        usage = raw.usage_metadata or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cost = calculate_cost(input_tokens, output_tokens, self.settings)
        generation_id = str(
            raw.response_metadata.get("id") or raw.id or ""
        )

        self.tracer.event(
            "llm_response",
            purpose=purpose,
            model=self.settings.openrouter_model,
            schema=schema.__name__,
            generation_id=generation_id,
            output=parsed.model_dump(),
            **cost.as_dict(),
        )
        return StructuredResult(
            value=parsed,
            cost=cost,
            generation_id=generation_id,
        )

    def _structured_model(self, schema: type[SchemaT]):
        # `include_raw=True` is important: the parsed object is convenient, but
        # the raw LangChain message contains the token counts needed for costs.
        return self.model.with_structured_output(
            schema,
            method="json_schema",
            strict=True,
            include_raw=True,
        )

    def _invoke_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ):
        """Wait on in-flight 402s. If the wallet can only reserve fewer
        output tokens, retry once at that cap. Empty-wallet 402s fail."""
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                return self._structured_model(schema).invoke(
                    [
                        SystemMessage(content=system_prompt),
                        HumanMessage(content=user_prompt),
                    ]
                )
            except Exception as exc:
                last_error = exc
                wait = in_flight_retry_seconds(exc)
                affordable = affordable_max_tokens(exc)
                if wait is not None and attempt < 2:
                    self.tracer.event(
                        "llm_retry",
                        error_type=type(exc).__name__,
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    time.sleep(wait)
                    continue
                if (
                    affordable is not None
                    and affordable < self._max_output_tokens
                    and attempt < 2
                ):
                    self.tracer.event(
                        "llm_retry",
                        error_type=type(exc).__name__,
                        max_tokens=affordable,
                        attempt=attempt + 1,
                    )
                    self._max_output_tokens = affordable
                    self.model = self._make_model()
                    continue
                raise
        raise last_error or RuntimeError("OpenRouter call failed")


def in_flight_retry_seconds(exc: BaseException) -> int | None:
    """Seconds to wait on an OpenRouter in-flight budget 402, else None."""
    text = str(exc)
    if "in_flight_budget" not in text:
        return None
    match = re.search(r"Retry-After['\"]?\s*[:=]\s*['\"]?(\d+)", text)
    if match:
        return min(max(int(match.group(1)), 5), 180)
    return 120


def affordable_max_tokens(exc: BaseException) -> int | None:
    """Output-token reservation OpenRouter says the remaining wallet can cover."""
    text = str(exc)
    if "can only afford" not in text.casefold():
        return None
    match = re.search(r"can only afford (\d+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    affordable = int(match.group(1))
    if affordable < 400:
        return None
    return affordable
