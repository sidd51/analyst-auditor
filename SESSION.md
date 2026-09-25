# Session log

## 21/09/2026

- Cursor first suggested TypeScript + Gemini as Project Stack.
- I choose **Python + OpenRouter** instead, because I wanted to practice Python more and OpenRouter provides wide variety of models.

### Step 2

- prompt_tokens / completion_tokens: 40 / 13
- cost_usd / cost_inr: 1.38e-05 / 0.0012
- The JSON came back as `{"ping":"pong",...}`

### Step 3 — search and fetch

- I used **DuckDuckGo (**`ddgs`**)** instead of Brave Search.
- Why not Brave: Brave needs an API key while `ddgs` is free and I wanted minimal setup.
- What I am trading off: DuckDuckGo is unofficial. The result keys were `href` and `body`, not `url` and `snippet`, so my first run printed `None` for links. Brave would be more stable if `ddgs` starts failing.
- Fetch: first Wikipedia extract was mostly the menu. I strip `nav` / `header` / `footer` and prefer `<main>` so the analyst gets article text and not some useless stuff.

### Step 4 — analyst loop (before extract)

- Plan-before-search works. The model returns queries to run.
- Search + fetch also sometimes works with`ddgs` . Best page so far: `titancompany.in/leadership-team` (Ajoy Chawla MD, Arun Narayan CEO Jewellery).

#### Why I did not switch to Brave
- I tried. Brave Search API asks for card details, which as a student I didn't had
- Cursor suggested Wikipedia API / OpenRouter web as a backup. I chose to **keep `ddgs`** instead of adding another paid path and keeping it simple.

#### Shortcomings I already know 
1. **`ddgs` is flaky.** Same queries: first run got Wikipedia + titancompany.in, next run timed out and printed empty `URLS:`.Because I think its is unofficial HTML scraping and not a real API. 
2. **`ddgs` is not only DuckDuckGo.** Default `auto` even hit Brave’s public HTML page, then timed out — without a Brave key.
3. **Retrying search is the real failure.** `run_fetches` plans + searches again every time. That burns the rate limit.
4. **Empty “successful” fetches.** `titancompany.in/node/2412` was `ok: True` but no text (JS/thin page). `ok` is not the same as evidence.
7. **We only fetch the first 3 URLs.** Later links (Tanishq Wikipedia, etc.) never get opened.
8. **No parallel search/fetch yet.** The loop is still one-after-another, so a timeout feels like a hang.
9. **Wikipedia/Yahoo “No results found” looks like a crash** in the log even when the next backend works. 

### Extraction of Claims
-So, while extracting claims I am limiting the page content to 3000 characters `"text": page["text"][:3000]` 
Two cuts already exist:

`fetch_page(..., max_chars=5000)` — page is chopped when you download
`page["text"][:3000]` — chopped again before the model sees it

ShortComing: The MD/CEO line might be much lower, so the model never sees it and says not_found even though the page had the name.

So: yes, a blunt cap loses context. No, unlimited text is not the fix because cost increase per token.

Only when the cost was not an issue, I wished to send full pages as context to avoid the not-found message to user.

### I am doing parallel fetch using ThreadPoolExecutor

## I am restarting the project there were too many shortcoming in the previous architecture