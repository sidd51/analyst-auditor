# Session log
## 21/09/2026
- Cursor first suggested TypeScript + Gemini as Project Stack.
- I choose **Python + OpenRouter** instead, because I wanted to practice Python more and OpenRouter provides wide variety of models.

### Step 2
- prompt_tokens / completion_tokens: 40 / 13
- cost_usd / cost_inr: 1.38e-05 / 0.0012
- The JSON came back as `{"ping":"pong",...}`

### Step 3 — search and fetch
- I used **DuckDuckGo (`ddgs`)** instead of Brave Search.
- Why not Brave: Brave needs a second API key. I already have OpenRouter. `ddgs` is free, no extra signup, and it is already in `requirements.txt`. I wanted the smallest setup that still hits the live web.
- What I am trading off: DuckDuckGo is unofficial. The result keys were `href` and `body`, not `url` and `snippet`, so my first run printed `None` for links. A real search API (Brave) would be more stable if `ddgs` starts failing. `.env.example` still has an optional `BRAVE_API_KEY` if I need to switch later.
- Fetch: first Wikipedia extract was mostly the menu. I strip `nav` / `header` / `footer` and prefer `<main>` so the analyst gets article text, not chrome.
