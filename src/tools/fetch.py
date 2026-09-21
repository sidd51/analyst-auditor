"""Open a URL and return readable text."""

import httpx
from bs4 import BeautifulSoup  # turn HTML into readable text

USER_AGENT = "analyst-auditor/0.1 (research project)"

def fetch_page(url: str, max_chars: int = 5000) -> dict:
  """Download a page. Return {url, ok, text, error}. """
  try:
    response = httpx.get(
      url,
      headers = {
        "User-Agent": USER_AGENT,
      },
      timeout = 20.0,
      follow_redirects = True,
    ) 
    response.raise_for_status()
  except httpx.HTTPStatusError as e:
    return {
      "url": url,
      "ok": False,
      "text": "",
      "error": f"HTTP error: {e}",
    }
  soup = BeautifulSoup(response.text, "lxml")
  for tag in soup(["script", "style", "noscript", "nav", "footer", "header"]):
    tag.decompose()

  article = soup.find("main") or soup.find("article") or soup
  text = " ".join(article.get_text(separator=" ").split())
  return {
    "url": url,
    "ok": True,
    "text": text[:max_chars],
    "error": "",
  }


if __name__ == "__main__":
    page = fetch_page("https://en.wikipedia.org/wiki/Tanishq")
    print("ok:", page["ok"])
    print("error:", page["error"])
    print("chars:", len(page["text"]))
    print(page["text"][:400])
  


