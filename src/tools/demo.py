"""Search, then open the first result."""

from src.tools.search import websearch
from src.tools.fetch import fetch_page

if __name__ == "__main__":
    hits = websearch("Tanishq number of stores in India 2025", max_results=3)
    if not hits:
        print("No search results")
        raise SystemExit(1)

    first = hits[0]
    print("title:", first["title"])
    print("url:", first["url"])
    print()

    page = fetch_page(first["url"])
    print("fetch ok:", page["ok"])
    print("error:", page["error"])
    print(page["text"][:300])