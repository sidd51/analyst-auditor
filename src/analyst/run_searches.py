"""Take the plan and actually search the web."""

from src.analyst.plan import make_plan
from src.config import load_settings
from src.llm import OpenRouterLLM
from src.tools.search import websearch
from src.trace import Tracer


def run_searches(plan: dict, tracer: Tracer) -> list[dict]:
    all_hits = []
    for query in plan["searches"]:
        tracer.event("tool_call", tool="web_search", query=query)
        hits = websearch(query, max_results=3)
        if not hits:
          tracer.event(
            "course_change",
            reason="search returned no hits, trying the next query",
            query=query,
          )
        tracer.event(
            "tool_result",
            tool="web_search",
            query=query,
            n=len(hits),
            urls=[h["url"] for h in hits],
        )
        all_hits.extend(hits)
    return all_hits


if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step4-search.jsonl")
    llm = OpenRouterLLM(settings, tracer)

    question = (
        "Who is the current MD or CEO of Titan Company "
        "(parent of Tanishq)? Cite a source."
    )
    plan = make_plan(question, llm)
    print("PLAN:", plan["searches"])
    print()

    hits = run_searches(plan, tracer)
    for i, hit in enumerate(hits, start=1):
        print(f"{i}. {hit['title']}")
        print(f"   {hit['url']}")
        print()