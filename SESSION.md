# Session
I took help of Cursor Agent.
## 21 Sep 2026 — stack

Cursor first suggested TypeScript + Gemini.
I chose Python + OpenRouter instead. I wanted more Python practice, and OpenRouter lets me swap models with one key.

### Earlier Architecture
I used DuckDuckGo (`ddgs`) instead of Brave Search for Search.
Why not Brave: Brave Search API asked for card details.
What I traded: DuckDuckGo is unofficial. The result keys were `href` and `body`, not `url` and `snippet`, so my first run printed `None` for links. Brave would be more stable if `ddgs` starts failing.

Fetch: the first Wikipedia extract was mostly the menu. I strip `nav` / `header` / `footer` and prefer `<main>` so the analyst gets article text.

### Shortcomings I wrote down on the first architecture

1. `ddgs` is flaky. Same queries: first run got Wikipedia + titancompany.in, next run timed out and printed empty URLs. It is unofficial HTML scraping, not a real API.
4. Empty “successful” fetches. `titancompany.in/node/2412` was `ok: True` but no text (JS / thin page). 
5. We only fetched the first 3 URLs. Later links never got opened.
6. I limited page content to 3000 characters (`page["text"][:3000]`).
There were two cuts:
- `fetch_page(..., max_chars=5000)` — chopped on download
- `page["text"][:3000]` — chopped again before the model
The MD/CEO line must be somewhere lower on the page.But,the model said `not_found` even though the name was on the page.

## I restarted
There were too many structural faults.
Cursor would have patched some of the faults up.

What I wanted in the new build:
# The new Architecture:
Stack : Python, Langchain - for easy orchestration, Pydantic - structured schemas, Tavily/DDGS - search 

- specify the question (entities, fields, dates) through a small LLM call before planning --this would help answer what was really asked and required.
- Tavily as primary search, DDGS only as fallback cause DDGS was flaky. 
- To encounter the problem of Context cutoff I introduced a conditional check for waves of pages, initially 5 pages each url then +4 if required fields are missing, never more than 15.
-instead of first-3000 clip — the pages were split into passages and scored against the required fields and only the best passages were sent to Analyst. 
- plan before any search that returned 2 to 4 focused queries tagged to  a specific requirement 
- these changes were done because in earlier architecture the queries were kind of irrelevant and did not contribute to the expected answer.
- This was my consious decision that, python decides whether the answer is complete.

### I made the final block a **Python gate**: 
only Auditor-`SUPPORTED` claims are shown. Missing and disputed stay visible. There is no extra model call after the auditor.

## Analyst tense — I kept the strict rule
Jewellery pages are full of “will open” and “plans to add.” I did not let those become claims.

Live Q04 asked for Titan’s store-addition *plan*. Analyst returned 0 claims.That is what the rule is supposed to do.

Cursor suggested to loosened `will` / `plans` so the score looked better.
I did not. I **changed the question** to something the open web actually states: whom Ajoy succeeded, and when that person retired.

## Eval
I ran `python -m src.eval.run --fresh`.
Q01–Q04 (or similar) spent the in-flight budget. Q05–Q08 died on OpenRouter 402 (`Retry-After: 120`).
Later Q08 died again: not in-flight — the wallet could only reserve 368–1782 tokens against a 2000 max.

I ran the naive baseline myself:

```bash
python -m src.eval.naive --qid Q01
python -m src.eval.naive --qid Q03
```

Naive Q01: C.K. Venkataraman, 1 Oct 2020, board-page URL.
Loop Q01: Ajoy Chawla, 1 Jan 2026.
Naive was ₹0.02 / 3s. Loop was ₹0.37 / 22s.
I keep the loop because the cheap answer is a year out of date.

Naive Q03 and the loop Q03 were both empty. Naive: cutoff. Loop: no quoted “opened.” I prefer the second kind of empty.

## After the scoreboard 
- Q03: 0 claims, 143s. Wave 2 still ran. I will not turn plans into openings.
- Cost: Q01 ₹0.37 → Q08 ₹0.34 (8%), not half. Skip fired once on Q06/Q07/Q08. That is not a cost win.
- Auditor table this run: all `SUPPORTED`, no `CONTRADICTED`. Analyst already drops unquoted drafts. The auditor checks the citation, not “did we answer the question.”

