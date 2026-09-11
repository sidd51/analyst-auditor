# Analyst + Auditor

Research agents for the Thuli Studios take-home: an **analyst** that answers live-web questions with citations, and an **auditor** that independently checks every claim.

Python. OpenRouter. No LangChain.

## Gate (reviewer — after all steps)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then set OPENROUTER_API_KEY
python -m src.check_setup
python -m src.eval.run
```

Logs land in `logs/`. The write-up is `WRITEUP.md`. The cost table is `reports/cost.md`.

Right now only Step 1 exists. `src.eval.run` will appear in Step 6.

## Your setup (Step 1 — do this now)

1. Create a free/paid key at [openrouter.ai/keys](https://openrouter.ai/keys).
2. In a terminal **in this folder**, run:

```bash
cd /Users/admin/analyst-auditor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

3. Open `.env` and paste your key. Leave the model as `openai/gpt-4o-mini` unless you want a different one.
4. Run:

```bash
python -m src.check_setup
```

5. If it prints `Step 1 init is done`, tell me **step 1 done**. We will not write agent code until that check passes on your machine.

## What this repo is not yet

Steps 2–7 (LLM wrapper, search tools, analyst, auditor, eight questions, write-up) are not here until we build them with you.

`STEPS.md` is the requirement checklist mapped onto those steps. `plan.md` is a local study sheet and is not committed.
