"""Live web search. Returns URL, title, and snippet."""
import time
from ddgs import DDGS
from ddgs.exceptions import DDGSException



def websearch(query: str, max_results: int = 3) -> list[dict]:
    """Try a few search backends. Return [] if all of them fail."""
    rows = []
    for backend in ("wikipedia", "yahoo", "duckduckgo"):
        try:
            with DDGS(timeout=8) as ddgs:
                rows = ddgs.text(
                    query,
                    max_results=max_results,
                    backend=backend,
                )
        except DDGSException as exc:
            print(f"search failed ({backend}) for {query!r}: {exc}")
            rows = []
            time.sleep(2)
        if rows:
            print(f"search ok ({backend}) for {query!r}")
            break

    results = []
    for row in rows:
        results.append(
            {
                "title": row.get("title") or "",
                "url": row.get("href") or "",
                "snippet": row.get("body") or "",
            }
        )
    return results

if __name__ == "__main__":
  hits = websearch("Tanishq number of stores in India 2025")
  for i , hit in enumerate(hits, start=1):
    print(f"{i}. {hit['title']}")
    print(f"   {hit['url']}")
    print(f"   {hit['snippet']}\n")