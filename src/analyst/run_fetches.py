"""Search, then open a few unique URLs."""

from src.analyst.plan import make_plan
from src.analyst.run_searches import run_searches
from src.config import load_settings
from src.llm import OpenRouterLLM
from src.tools.fetch import fetch_page
from src.trace import Tracer
from concurrent.futures import ThreadPoolExecutor, as_completed


def unique_urls(hits: list[dict]) -> list[str]:
    seen = []
    for hit in hits:
        url = hit.get("url") or ""
        if url and url not in seen:
            seen.append(url)
    return seen


def run_fetches(urls: list[str], tracer: Tracer, limit: int = 3) -> list[dict]:
    chosen = []
    for url in urls[:limit]:
        if "linkedin.com" in url:
            tracer.event("course_change", reason="skip LinkedIn login wall", url=url)
            continue
        chosen.append(url)
        tracer.event("tool_call", tool="fetch_page", url=url)

    pages = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_url = {pool.submit(fetch_page, url): url for url in chosen}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                page = future.result()
            except Exception as exc:
                page = {"url": url, "ok": False, "text": "", "error": str(exc)}
            tracer.event(
                "tool_result",
                tool="fetch_page",
                url=url,
                ok=page["ok"],
                error=page.get("error") or "",
            )
            if not page["ok"]:
                tracer.event("course_change", reason="fetch failed, skip page", url=url)
            pages.append(page)
    return pages

if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step4-fetch.jsonl")
    llm = OpenRouterLLM(settings, tracer)

    question = (
        "Who is the current MD or CEO of Titan Company "
        "(parent of Tanishq)? Cite a source."
    )
    plan = make_plan(question, llm)
    hits = run_searches(plan, tracer)
    urls = unique_urls(hits)
    print("URLS:")
    for url in urls:
        print("-", url)
    print()

    pages = run_fetches(urls, tracer)
    for page in pages:
        print("ok:", page["ok"], "url:", page["url"])
        print((page.get("text") or "")[:250])
        print()