"""Live web search. Returns URL, title, and snippet."""

from ddgs import DDGS

def websearch(query: str, max_results: int = 3) -> list[dict]:
  """Ask DuckDuckGo. Each item is a dict with URL, title, and snippet."""
  results=[]
  with DDGS() as ddgs:
    for row in ddgs.text(query, max_results=max_results):
      results.append({
        "title": row.get("title") or "",
        "url": row.get("href") or "",
        "snippet": row.get("body") or "",
      })
  return results

if __name__ == "__main__":
  hits = websearch("Tanishq number of stores in India 2025")
  for i , hit in enumerate(hits, start=1):
    print(f"{i}. {hit['title']}")
    print(f"   {hit['url']}")
    print(f"   {hit['snippet']}\n")