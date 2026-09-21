"""The only place we talk to OpenRouter.

Later the analyst and auditor both call `complete_json`. Cost and traces stay
honest because they cannot bypass this wrapper.
"""

from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from src.config import Settings
from src.cost import CostRecord
from src.trace import Tracer


class OpenRouterLLM:
    def __init__(self, settings: Settings, tracer: Tracer | None = None) -> None:
        self.settings = settings
        self.tracer = tracer
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/sidd51/analyst-auditor",
                "X-Title": "analyst-auditor",
            },
        )

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> tuple[str, CostRecord]:
        kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        if self.tracer:
            self.tracer.event(
                "llm_request",
                purpose=purpose,
                model=self.settings.model,
                json_mode=json_mode,
                message_count=len(messages),
            )

        response = self.client.chat.completions.create(**kwargs)
        text = (response.choices[0].message.content or "").strip()
        cost = _cost_from_response(response, self.settings.model)

        if self.tracer:
            self.tracer.event(
                "llm_response",
                purpose=purpose,
                model=cost.model,
                generation_id=cost.generation_id,
                prompt_tokens=cost.prompt_tokens,
                completion_tokens=cost.completion_tokens,
                cost_usd=cost.cost_usd,
                cost_inr=cost.cost_inr(self.settings.usd_inr_rate),
                chars=len(text),
            )
        return text, cost

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        temperature: float = 0.0,
    ) -> tuple[dict[str, Any], CostRecord]:
        text, cost = self.complete(
            messages,
            purpose=purpose,
            json_mode=True,
            temperature=temperature,
        )
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model did not return JSON for {purpose}: {text[:300]}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"JSON for {purpose} was not an object: {parsed!r}")
        return parsed, cost


def _cost_from_response(response: Any, model: str) -> CostRecord:
    usage = getattr(response, "usage", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    completion = int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0
    cost_usd = 0.0
    if usage is not None:
        raw = getattr(usage, "cost", None)
        if raw is None:
            extra = getattr(usage, "model_extra", None) or {}
            raw = extra.get("cost") if isinstance(extra, dict) else None
        if raw is not None:
            cost_usd = float(raw)
    return CostRecord(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_usd=cost_usd,
        model=getattr(response, "model", None) or model,
        generation_id=getattr(response, "id", "") or "",
    )
