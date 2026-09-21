"""Ask the model HOW to search. Do not search yet."""

from src.config import load_settings
from src.llm import OpenRouterLLM
from src.trace import Tracer

PLAN_INSTRUCTIONS = """
You are a research planner. Do not answer the user'squestion.
Return a JSON object with:
- "searches": 2 to 4 short web search queries
- "not_found_means": one sentence on what we should admit we don't know if the sources do not say it

"""


def make_plan(question: str, llm: OpenRouterLLM) -> dict:
    payload, _cost = llm.complete_json(
        [
            {"role": "system", "content": PLAN_INSTRUCTIONS},
            {"role": "user", "content": question},
        ],
        purpose="plan",
    )
    return payload


if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step4-plan.jsonl")
    llm = OpenRouterLLM(settings, tracer)

    question = (
        "Who is the current MD or CEO of Titan Company "
        "(parent of Tanishq)? Cite a source."
    )
    plan = make_plan(question, llm)
    print(plan)
    print("trace:", settings.root / "logs" / "step4-plan.jsonl")
