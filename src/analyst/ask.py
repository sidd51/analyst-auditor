"""One function: question in, claims out."""

from src.analyst.extract import extract_claims
from src.analyst.plan import make_plan
from src.analyst.run_fetches import run_fetches, unique_urls
from src.analyst.run_searches import run_searches
from src.config import load_settings
from src.llm import OpenRouterLLM
from src.trace import Tracer
from src.memory.store import remembered_texts


def ask(question: str, llm: OpenRouterLLM, tracer: Tracer) -> dict:
    tracer.event("question", text=question)
    remembered = remembered_texts()
    if remembered:
      tracer.event("memory_loaded", facts=remembered)
    plan = make_plan(question, llm, remembered=remembered)
    tracer.event("plan", plan=plan)
    hits = run_searches(plan, tracer)
    pages = run_fetches(unique_urls(hits), tracer)
    extracted = extract_claims(question, pages, llm)
    return {
        "question": question,
        "plan": plan,
        "claims": extracted.get("claims") or [],
    }


if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step4-ask.jsonl")
    llm = OpenRouterLLM(settings, tracer)
    question = (
        "Who is the current MD or CEO of Titan Company "
        "(parent of Tanishq)? Cite a source."
    )
    answer = ask(question, llm, tracer)
    print(answer["claims"])