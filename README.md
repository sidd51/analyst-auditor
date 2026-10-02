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

**Live Evaluation screen :** [sidd51.github.io/analyst-auditor](https://sidd51.github.io/analyst-auditor/)

Locked set in [`src/eval/questions.py`](src/eval/questions.py): 

Q01 → Q06 is the Titan memory-verify pair. Q05 → Q08 is the RBI pair.


|        | Cold Q01 | Memory-verify Q06 |
| ------ | -------- | ----------------- |
| Tokens | 5,786    | 2,574             |
| Time   | 22.1s    | 7.8s              |
| Cost   | ₹0.35    | ₹0.19             |

Q06 reopens stored MD citation URLs (no plan, search, or wave 2).


|             | Naive Q01 [no tools]        | Loop Q01                |
| ----------- | --------------------------- | ----------------------- |
| Answer      | C.K. Venkataraman, Oct 2020 | Ajoy Chawla, 1 Jan 2026 |
| Cost / time | ₹0.02 / 3s                  | ₹0.35 / 22s             |

The additional cost buys a research/verification capability that the naive approach lacks.


| Q   | complete | tokens | ₹    | sec  | memory facts | SUPPORTED | UNSUPPORTED | missing |
| --- | -------- | ------ | ---- | ---- | ------------ | --------- | ----------- | ------- |
| Q01 | yes      | 5786   | 0.35 | 22.1 | 0            | 2         | 0           | 0       |
| Q02 | yes      | 9425   | 0.46 | 21.6 | 3            | 2         | 0           | 0       |
| Q03 | yes      | 14634  | 0.84 | 30.2 | 0            | 6         | 0           | 0       |
| Q04 | yes      | 7615   | 0.43 | 18.5 | 1            | 2         | 0           | 0       |
| Q05 | yes      | 13245  | 0.77 | 40.1 | 0            | 4         | 0           | 0       |
| Q06 | yes      | 2574   | 0.19 | 7.8  | 4            | 2         | 0           | 0       |
| Q07 | no       | 17996  | 1.09 | 43.2 | 4            | 7         | 0           | 1       |
| Q08 | yes      | 5650   | 0.30 | 11.5 | 8            | 2         | 0           | 0       |
| Q09 | no       | 7549   | 0.34 | 18.7 | 3            | 0         | 1           | 4       |


Full columns: `[reports/cost.md](reports/cost.md)`, `[reports/auditor.md](reports/auditor.md)`. Decisions and failures: `[WRITEUP.md](WRITEUP.md)`.


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
