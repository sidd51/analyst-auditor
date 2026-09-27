# Analyst + Auditor

This is a analyst and an independent auditor for open research questions requiring evidence gathered from the live web.
The system searches, fetches pages, and keeps a claim only when the quote is on that page.
The auditor re-opens the citations, Python decides if the answer is complete, and memory stores entity facts.

## Architecture

```text
USER QUESTION
    |
    v
SPECIFY          entities, required fields, as-of date, page policy
    |
    v
MEMORY READ      known / disputed facts for named entities only
                 never a previous final answer
    |
    v
PLAN             2–4 search queries; skip targets already known
    |
    v
SEARCH           Tavily, then DDGS; snippets are not evidence
    |
    v
FETCH WAVE 1     first 5 pages, parallel; leftovers kept
    |
    v
RETRIEVE         lexical passages into a token budget
    |
    v
ANALYST          quoted claims only; plans are not claims
                 unanswered fields stay unanswered
    |
    +-- if a required field is still open and leftovers remain
    |     FETCH WAVE 2   next 4 leftover URLs (no new search)
    |     ANALYST again  gap fields only
    |
    v
CROSS-CHECK      one extra search/fetch for single-domain claims
                 corroborated | single_source | conflicting
    |
    v
AUDITOR          refetch cited URLs 
                 SUPPORTED | UNSUPPORTED | CONTRADICTED | UNCITED
    |
    v
PYTHON GATE      only SUPPORTED claims are shown
                 complete is not an LLM decision
    |
    +--> MEMORY WRITE    accepted facts; disputed/rejected as notes
    |
    v
FINAL ANSWER     accepted / missing / disputed + citations
```

Page budget: 5, then +4 if fields are missing, never more than 15.


## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put `OPENROUTER_API_KEY` in `.env`. `TAVILY_API_KEY` is optional; DDGS
runs without it. Then:

```bash
python -m src.check_setup
pytest -q
```

## Assess without a live run

Committed traces and tables are the scored artifact:

| What | Where |
|------|--------|
| Full Q1–Q8 traces | `logs/q01-analyst.jsonl` … `logs/q08-analyst.jsonl` |
| One-shot baseline (no search) | `logs/q01-naive.jsonl`, `logs/q03-naive.jsonl` |
| Cost / time / memory skip | `reports/cost.md` |
| Auditor verdicts | `reports/auditor.md` |
| Locked questions | `src/eval/questions.py` |

```bash
python -m src.eval.report
```

rebuilds the two report files from those traces (no API calls).

## Live commands (paid)

One question:

```bash
python -m src.analyze \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and the effective appointment date."
```

All eight, shared memory (writes `logs/qNN-analyst.jsonl`):

```bash
python -m src.eval.run --fresh
```

Resume a subset without wiping memory:

```bash
python -m src.eval.run --only Q08
```

Naive one-shot (no tools):

```bash
python -m src.eval.naive --qid Q01
```
