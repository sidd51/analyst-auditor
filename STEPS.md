# Build steps (you init each one)

We stop after every step. You run the commands. You paste keys. You say when it worked.

This file is the **requirement map**, not just a todo list. If a row in the
coverage table has no step, we are failing the brief.

## How they grade (so we do not optimize the wrong thing)

1. **Gate.** Clean checkout + README only. Logs and write-up must be **in git**.
   If that fails, they stop reading.
2. **Code.** Analyst + auditor actually run. Tools are real. Memory is real.
3. **Logs.** Full traces, not screenshots of the final answer.
4. **Write-up.** Why it is built this way. Weaknesses named. One approach
   tried, measured, rejected.
5. **Session.** You lead. You overrule the tool at least once. `SESSION.md`
   is in your words.

The write-up carries more weight than most people assume. The 45-minute call
is "change your own system live." If you cannot explain a file, we delete it.

---

## Requirement coverage

### Part A — analyst (core, not optional)

| Requirement | Where we build it | How we know it is done |
|-------------|-------------------|------------------------|
| Open research questions that one model call cannot answer | Step 4 + Step 6 | Jewellery / funding / people questions, not trivia |
| Plan an approach **before** searching | Step 4 | Trace has a `plan` event with **zero** tool calls before it |
| Real **web search** tool | Step 3 | Tool returns live titles + URLs |
| Real **page fetch** tool | Step 3 | Tool returns page text, not a model hallucination |
| Run work **in parallel** where it makes sense | Step 4 | Several searches or fetches overlap in the trace timestamps |
| Cross-check claims that appear in **only one source** | Step 4 | Extra search/fetch after a single-source claim |
| Memory across questions (later question faster **and** better) | Step 5 + 6 | Q4 and Q8 reuse Titan/Kalyan/etc. Fewer searches, not a pasted old answer |
| Every answer has **citations** | Step 4 | Each claim has URLs or is marked `not_found` |
| Say **cannot find** instead of guessing | Step 4 | At least one field in the 8-question run is `not_found` on purpose |
| **Eight** questions, increasing difficulty | Step 6 | `src/eval/questions.py` |
| **At least two** questions reuse earlier entities | Step 6 | Q4 and Q8 |

### Part B — auditor (core, not optional)

| Requirement | Where we build it | How we know it is done |
|-------------|-------------------|------------------------|
| Second agent, independent of the analyst | Step 5 | No shared page cache. Auditor fetches URLs itself |
| Open the **cited** source | Step 5 | Trace shows `fetch_page` on the claim's URL |
| Mark **supported / unsupported / contradicted** | Step 5 | Verdict enum in the JSONL |
| Flag claims with **no citation** | Step 5 | `uncited` verdict |
| Run auditor on **our** analyst answers | Step 6 | `reports/auditor.md` |
| Report what it caught | Step 6 + 7 | At least one real catch. Rubber-stamp auditor = fail |
| Honest limits | Step 7 | Paywalls, JS pages, PDFs, keyword-overlap ≠ support |

### What they want to see (core)

| Requirement | Where we build it | How we know it is done |
|-------------|-------------------|------------------------|
| Full trace per question: plan, every tool call, what came back, course-change after failure | Step 2–6 | `logs/qNN-analyst.jsonl` and `logs/qNN-auditor.jsonl` |
| Cost per question in **tokens and rupees** | Step 2 + 6 | `reports/cost.md` |
| Trend across eight questions | Step 6 | Table Q1→Q8 |
| Gets cheaper and faster as it learns | Step 5 + 6 | Mechanism = entity memory + quote-first prompts, **not** answer cache |
| What we changed between runs and why | Step 6 + 7 | `WRITEUP.md` + `SESSION.md` |

### Take it further (pick **one** and do it properly)

Assignment says: solve one properly rather than four loosely.

| Stretch | Decision | Why |
|---------|----------|-----|
| Cost drops by **half** with no loss of correctness. Memory that transfers to a **new** question. Caching an old answer does **not** count | **Do this** (tied to Step 5–6) | They already asked for cheaper-as-it-learns in the core. We make the mechanism measurable |
| Auditor findings feed back into the analyst automatically (no hand-editing the prompt) | **Do this** — it is the same loop | Unsupported facts are stored as `rejected`. Next planner does not reuse them. Closest thing on the page to what they actually build |
| Sources that disagree: resolve and justify, do not shrug | **Do this as one of the 8 questions** (Q7) | Jewellery store counts always disagree. Cheap to include, high signal |
| Hard **2 minute** ceiling per question | **Measure, do not hard-kill in v1** | We log wall-clock. A fake timeout that cuts answers in half is worse than honest numbers. Revisit if Step 6 traces are already parallel |
| Make the analyst adversarial (tell it an auditor will check) | **Skip unless time** | Fourth stretch. Doing it loosely is what they told us not to do |

### Assessment gate (submission)

| Requirement | File | Step |
|-------------|------|------|
| Runs from clean checkout using only README | `README.md` | 1, then 6 |
| Logs in the repo | `logs/*.jsonl` | 6 (**must be committed**, not gitignored) |
| Write-up in the repo | `WRITEUP.md` | 7 |
| Write-up is **why**, not a code tour | `WRITEUP.md` | 7 — **you** draft it |
| Named weakness, not vague | `WRITEUP.md` | 7 |
| Obvious approach tried, measured, rejected | Step 6 experiment | One-shot "just ask OpenRouter to search" vs our loop, with numbers |
| You overrule the tool once | `SESSION.md` | ongoing |

`plan.md` in this folder is **your** study sheet. It is gitignored. Reviewers never see it.

---

## The eight questions (locked for Step 6)

Increasing difficulty. Two reuse entities. One disagreement.

1. Who is the current MD/CEO of Titan Company (Tanishq parent)? Cite a source.
2. How many Tanishq stores did Titan last report, and for which period?
3. Which three Indian jewellery retailers opened the most new stores in the last two years, and what is the evidence for each?
4. **Reuse Titan:** given memory, what is Titan's stated store-addition plan for the current fiscal year?
5. List notable Indian jewellery or quick-commerce funding rounds since January this year (company, amount, investors, date). `not_found` is allowed per field.
6. For a named company from Q3: current head of engineering / CTO, when they joined, where they worked before.
7. **Disagreement:** two credible sources give different store counts for Malabar or Kalyan. Choose one. Justify. Do not report both and shrug.
8. **Reuse + transfer:** using memory plus a small verify pass, which of {Titan, Kalyan, Q3 #1} is expanding faster, and what evidence would change your mind?

---

## Step table (you init each one)

| Step | What we build | You init (required before I code the next step) | Brief rows it covers |
|------|----------------|--------------------------------------------------|----------------------|
| **1** | Repo, venv, OpenRouter key, `python -m src.check_setup` | Create key, `.env`, run the check, fill **Why** in `SESSION.md` | Gate setup |
| **2** | OpenRouter wrapper: JSON answers, token counts, rupees | Confirm `OPENROUTER_MODEL`. Run a tiny paid ping. Read the rupee line | Cost in tokens + INR |
| **3** | `web_search` + `fetch_page` | Optional Brave key. Run one search and one fetch yourself | Real tools |
| **4** | Analyst loop: **plan first**, parallel search/fetch, extract quotes, cross-check single-source, citations or `not_found` | Pick Q1. We run it together. You point at the `plan` event in the JSONL | Part A minus memory |
| **5** | Auditor (independent fetch + verdicts) + entity memory + auditor write-back | We audit Q1. You confirm it caught or missed something. You say whether rejected facts should be blocked next time (yes) | Part B + stretch feedback loop |
| **6** | All 8 questions, traces, cost table, naive-vs-loop experiment | You read Q4 and Q8 traces and say whether memory actually transferred. We only then tune | Eight questions, reuse, disagreement, cost trend, rejected shortcut |
| **7** | `WRITEUP.md`, `reports/auditor.md`, email blurb | **You write the write-up.** I only supply the table of numbers. You send the email | Gate + Yes-pile write-up |

Do not skip ahead. Reply `step N done` after you have run that step's init.

---

## What would fail even if the code "works"

- One OpenRouter call with "please search the web" and no plan event
- Caching the text of Q3 and pasting it as Q8 (they said this does not count)
- Auditor that marks everything `supported`
- Guessing a CTO name with a LinkedIn URL you never fetched
- Empty `logs/` on GitHub because it was gitignored (this was a bug in the first `.gitignore`; fixed)
- `WRITEUP.md` that only restates the code
- Me writing every decision in `SESSION.md` for you
