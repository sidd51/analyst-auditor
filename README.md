# Analyst + Auditor

Thuli take-home: a research **analyst** and an independent **auditor**.

Python. OpenRouter via LangChain. Plain Python orchestration.

The project is built in small stages. Steps 1–2 currently provide validated
configuration, LangChain structured output, token costs, and JSONL tracing.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your OpenRouter key in `.env`. A free Tavily key is optional in Step 1 but
will be needed as the primary search provider in the search step:

```bash
python -m src.check_setup
```

You should see `Step 1 setup is ready`.

Run the offline configuration tests:

```bash
pytest -q
```

## Step 2 — tiny structured-output ping

This command makes one small paid OpenRouter call:

```bash
python -m src.ping
```

It validates the model response with Pydantic, prints input/output tokens and
estimated USD/INR cost, and writes `logs/step2-ping.jsonl`.

## Step 3A — bounded web search

Search uses Tavily first and falls back once to DDGS when Tavily fails or
returns no usable links:

```bash
python -m src.tools.search "Titan Company managing director"
```

Each provider returns at most five normalized results. The command writes the
queries, snippets, failures, fallback decision, and URLs to
`logs/step3-search.jsonl`. Search snippets help discover pages; later steps
must still fetch the original URL before using it as evidence.

## Step 3B — parallel HTML/PDF fetching

Pass two or more search-result URLs to demonstrate parallel fetching:

```bash
python -m src.tools.fetch \
  "https://example.com/article-one" \
  "https://example.com/report.pdf"
```

The fetcher:

- deduplicates URLs and enforces the page budget;
- skips known login walls (Facebook, Instagram, LinkedIn, X/Twitter,
  YouTube, TikTok, Threads);
- fetches selected pages with `ThreadPoolExecutor`;
- uses Trafilatura for HTML and BeautifulSoup as fallback;
- uses `pypdf` for PDF text with page labels;
- records every result in `logs/step3-fetch.jsonl`.

## Step 3C — relevant passage retrieval

This combines fetching with deterministic passage selection:

```bash
python -m src.tools.retrieve \
  --question "Who is Titan Company's Managing Director in 2026?" \
  --requirement "Give the full name and effective date." \
  "https://example.com/article-one" \
  "https://example.com/article-two"
```

Documents are split into overlapping passages. Plain Python scores question
terms, preserves PDF page numbers, limits passages per source, and stops before
the evidence token budget is exceeded. The exact selected passages are written
to `logs/step3-retrieve.jsonl`. No LLM call occurs in this step.

## Step 4A — question specification

This command makes one small paid OpenRouter call:

```bash
python -m src.specify \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and effective appointment date."
```

The model extracts entities, required fields, dates, geography, ranking, and
not-found rules. Python attaches an as-of date (`2026-09-26` by default),
resolves phrases such as "last two years" into an explicit range, and applies
the same page policy to every question:

- first wave: 5 pages
- later waves: 4 more pages only if required fields are still missing
- never exceed 15 pages

Question type does not change the first-wave budget. The command writes the
spec, policy, tokens, and cost to `logs/step4-specify.jsonl`.

## Step 4B — research planner

This command makes two small paid OpenRouter calls (specify, then plan):

```bash
python -m src.plan_research \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and effective appointment date."
```

The planner returns 2–4 focused queries, each tagged to a required field.
It must use the resolved date range and must not invent company names when
the spec only has a category such as "Indian jewellery retailers". Python
deduplicates queries and keeps at most four. Memory is empty in this step,
so the prompt says there are no known facts yet. No search or fetch happens
here. The plan is written to `logs/step4-plan.jsonl`.

## Step 4C — first-wave evidence

This command makes two paid OpenRouter calls, then live search and fetch:

```bash
python -m src.collect_evidence \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and effective appointment date."
```

It searches each planned query sequentially, deduplicates URLs, fetches the
first 5 pages in parallel, and retrieves relevant passages. Extra URLs stay
in `unused_urls` for a later wave. No extra LLM call happens after planning.
The run is written to `logs/step4-collect.jsonl`.

## Step 4D — Analyst claims

This command makes up to six paid OpenRouter calls, then live search and fetch:

```bash
python -m src.analyze \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and effective appointment date."
```

The Analyst may emit a claim only when a selected passage contains an exact
quote of an actual fact in the resolved period. A single in-window
opened/added number is still a claim even if a ranking cannot be finished.
Plans and guesses are not claims. Missing required fields and missing rank
slots are listed as `unanswered`. Python drops any draft whose quote is not
in the cited passage and keeps at most three short notes. Completeness is
not decided here. If a required field is still unanswered and leftover
search URLs remain, Python fetches the next 4 of those URLs (no new
search), retrieves passages for the gap, and runs one more Analyst pass.
Claims are merged, then the pipeline continues once. Easy questions that
already cover every required field stay at five model calls. After that,
single-domain claims are
cross-checked with one dedicated search and one independent fetch. A
wave-1 page is reused only when search selects that same URL and the
page is long enough. Contact-DB hosts, `/error-page` URLs, and almost
empty pages are skipped. The judge may use only the independent passage,
not the Analyst quote. Labels become `corroborated`, `single_source`, or
`conflicting`. After that, the Auditor refetches every unique cited URL
without using the Analyst page cache, retrieves fresh passages scored on
the claim text (not the quote), and judges each (claim, source) pair in
one batched call. Python rolls those notes up: `SUPPORTED` if at least
one cited source supports and none contradict, `UNSUPPORTED` if none
support, `CONTRADICTED` if a cited source disagrees on the same fact,
and `UNCITED` if there are no URLs. A silent or failed page is not a
conflict. Python then builds the user-facing answer: only `SUPPORTED`
claims are shown, with short citation labels. Required fields with no
verified claim, plus ranking slots that are short, go under `Missing`.
`CONTRADICTED` claims and cross-check `conflicting` labels go under
`Disputed`. `Answer (complete)` is printed only when every required
field survived and nothing is disputed. There is no extra model call.
Python then writes entity memory to `data/memory.json`: accepted facts
(including tagged `single_source` rows), plus `disputed` / `rejected`
notes. Whole answers are never stored. The next plan only sees facts
for entities named in that question. Disputed fields are not treated
as known. The run is written to `logs/step4-analyze.jsonl`.

## What stays out of this setup

No LangGraph, no LangSmith, no SQLite, no MCP, no vector database.
Those stay out on purpose so the later code stays small enough to explain live.
