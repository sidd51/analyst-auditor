# Analyst&Auditor
### Evidence-gated web research agent
Analyst- An agent that answers open research questions requiring evidence gathered from the live web.
Auditor- A second agent that takes an analyst answer and independently verifies.

## Features

- Quote-lock: a claim is kept only if its quote appears on the fetched page.
- Independent auditor: cited URLs are refetched and judged `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, or `UNCITED`.
- Python gate: completeness is a required-field check. The model does not write the final answer.
- Entity memory: Auditor supported facts only. If every required field is already known, reopen 1–2 stored URLs and skip a full search.
- Cite-a-page: that verify query is not dropped just because the fact is already in memory.
- Bounded fetch: 5 pages, then +4 if fields are still missing, never more than 15.
- Scored eval: nine live questions, naive baseline, cost and auditor tables from traces.

## Results (live eval, shared memory)

Nine scored questions. Traces in `logs/`. Tables rebuilt with `python -m src.eval.report` (no API calls).


|        | Cold Q01 | Memory-verify Q06 |
| ------ | -------- | ----------------- |
| Tokens | 5,173    | 3,051             |
| Time   | 25.9s    | 7.9s              |
| Cost   | ₹0.35    | ₹0.20             |

Q06 reopens 1–2 stored MD citation URLs.


|             | Naive Q01 [no tools]        | Loop Q01                |
| ----------- | --------------------------- | ----------------------- |
| Answer      | C.K. Venkataraman, Oct 2020 | Ajoy Chawla, 1 Jan 2026 |
| Cost / time | ₹0.02 / 3s                  | ₹0.35 / 26s             |

The additional cost buys a research/verification capability that the naive approach lacks.


| Q   | complete | tokens | ₹    | sec    | memory facts | SUPPORTED | UNSUPPORTED | missing |
| --- | -------- | ------ | ---- | ---- | ------------ | --------- | ----------- | ------- |
| Q01 | yes      | 5173   | 0.35 | 25.9 | 0            | 2         | 0           | 0       |
| Q02 | yes      | 14182  | 0.86 | 167  | 2            | 4         | 0           | 0       |
| Q03 | no       | 7822   | 0.39 | 20.5 | 0            | 0         | 0           | 3       |
| Q04 | yes      | 7919   | 0.43 | 21.5 | 3            | 2         | 0           | 0       |
| Q05 | yes      | 10839  | 0.59 | 24.6 | 0            | 4         | 0           | 0       |
| Q06 | yes      | 3051   | 0.20 | 7.9  | 3            | 2         | 0           | 0       |
| Q07 | no       | 3909   | 0.25 | 47.3 | 6            | 1         | 0           | 5       |
| Q08 | yes      | 9356   | 0.58 | 24.9 | 5            | 4         | 0           | 0       |
| Q09 | no       | 4022   | 0.22 | 50.4 | 8            | 0         | 1           | 2       |


Full columns: `[reports/cost.md](reports/cost.md)`, `[reports/auditor.md](reports/auditor.md)`. Decisions and failures: `[WRITEUP.md](WRITEUP.md)`.

Evaluation screen: [`ui/eval.html`](ui/eval.html) (rebuild with `python -m src.eval.report`).


### Architecture

```text
USER QUESTION
    |
    v
SPECIFY          entities, required fields, as-of date, page policy
    |
    v
MEMORY READ      known / disputed facts for named entities only
                 never a previous final answer
                 if every required field is already known, reopen
                 1–2 stored URLs (no search, no wave 2)
    |
    v
PLAN             2–4 search queries; skip targets already known
                 unless the question says to cite a page
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

Stack: Python, Langchain, Pydantic, OpenRouter, Tavily (DDGS fallback), Trafilatura / BeautifulSoup / pypdf.

### Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put `OPENROUTER_API_KEY` in `.env`. `TAVILY_API_KEY` is optional; DDGS runs without it.

```bash
python -m src.check_setup
pytest -q
```



### Run

One question (paid):

```bash
python -m src.analyze \
  "Who is Titan Company's Managing Director in 2026?" \
  --note "Give the full name and the effective appointment date."
```

All nine, shared memory:

```bash
python -m src.eval.run --fresh
```

Naive one-shot (no tools):

```bash
python -m src.eval.naive --qid Q01
```

Locked questions: `[src/eval/questions.py](src/eval/questions.py)`. Traces: `logs/q01-analyst.jsonl` … `logs/q09-analyst.jsonl`.
