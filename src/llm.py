"""Small LangChain wrapper used by both future agents."""

from __future__ import annotations

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
        self.model = ChatOpenAI(
            model=settings.openrouter_model,
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/sidd51/analyst-auditor",
                "X-Title": "Analyst-Auditor",
            },
            temperature=0,
            max_tokens=settings.max_model_output_tokens,
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

        # `include_raw=True` is important: the parsed object is convenient, but
        # the raw LangChain message contains the token counts needed for costs.
        structured_model = self.model.with_structured_output(
            schema,
            method="json_schema",
            strict=True,
            include_raw=True,
        )

        try:
            response = structured_model.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
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
