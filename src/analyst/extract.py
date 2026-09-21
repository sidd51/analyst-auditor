"""Turn fetched pages into cited claims. No guessing."""
from src.analyst.plan import make_plan
from src.analyst.run_fetches import run_fetches, unique_urls
from src.analyst.run_searches import run_searches
from src.config import load_settings
from src.llm import OpenRouterLLM
from src.trace import Tracer

EXTRACT_INSTRUCTIONS = """
You only use the page texts given to you.
Return JSON with key "claims", a list of objects:
- "text": one factual sentence
- "status": "supported" or "not_found"
- "url": the page URL if supported, else ""
- "quote": a short phrase copied from that page if supported, else ""
If the pages do not name the current MD or CEO, one claim must have
status "not_found". Do not invent names.
"""

def extract_claims(question: str, pages: list[dict], llm: OpenRouterLLM) -> dict:
    usable = [p for p in pages if p.get("ok") and (p.get("text") or "").strip()]
    packed = []
    for page in usable:
        packed.append(
            {
                "url": page["url"],
                "text": page["text"][:3000],
            }
        )
    payload, _cost = llm.complete_json(
        [
            {"role": "system", "content": EXTRACT_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n\nPages:\n{packed}"
                ),
            },
        ],
        purpose="extract",
    )
    return payload
if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step4-extract.jsonl")
    llm = OpenRouterLLM(settings, tracer)
    question = (
        "Who is the current MD or CEO of Titan Company "
        "(parent of Tanishq)? Cite a source."
    )
    plan = make_plan(question, llm)
    hits = run_searches(plan, tracer)
    pages = run_fetches(unique_urls(hits), tracer)
    result = extract_claims(question, pages, llm)
    print(result)
