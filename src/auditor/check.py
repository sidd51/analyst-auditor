"""Re-open cited URLs. Do not trust the analyst's page cache."""

import json

from src.config import load_settings
from src.llm import OpenRouterLLM
from src.tools.fetch import fetch_page
from src.trace import Tracer
from src.memory.store import write_supported

AUDIT_INSTRUCTIONS = """
You are an auditor. You only use the page text given here.
The analyst claimed something and gave a URL and a quote.
Return JSON with:
- "verdict": one of supported, unsupported, contradicted, uncited
- "reason": one short sentence
supported = the page clearly says the claim
unsupported = page does not say it (or page empty)
contradicted = page says the opposite
uncited = there was no URL
"""


def audit_claim(claim: dict, llm: OpenRouterLLM, tracer: Tracer) -> dict:
    url = (claim.get("url") or "").strip()
    if not url:
        tracer.event("audit", verdict="uncited", claim=claim.get("text"))
        return {"claim": claim, "verdict": "uncited", "reason": "no URL"}

    tracer.event("tool_call", tool="fetch_page", url=url, who="auditor")
    page = fetch_page(url)
    tracer.event(
        "tool_result",
        tool="fetch_page",
        who="auditor",
        url=url,
        ok=page.get("ok"),
    )

    payload, _cost = llm.complete_json(
        [
            {"role": "system", "content": AUDIT_INSTRUCTIONS},
            {
                "role": "user",
                "content": (
                    f"Claim: {claim.get('text')}\n"
                    f"Analyst quote: {claim.get('quote')}\n"
                    f"URL: {url}\n"
                    f"Page ok: {page.get('ok')}\n"
                    f"Page text:\n{(page.get('text') or '')[:3000]}"
                ),
            },
        ],
        purpose="audit",
    )
    verdict = payload.get("verdict") or "unsupported"
    tracer.event("audit", verdict=verdict, reason=payload.get("reason"), claim=claim.get("text"))
    return {"claim": claim, "verdict": verdict, "reason": payload.get("reason")}


if __name__ == "__main__":
    settings = load_settings()
    tracer = Tracer(settings.root / "logs" / "step5-audit.jsonl")
    llm = OpenRouterLLM(settings, tracer)
    path = settings.root / "data" / "last_answer.json"
    answer = json.loads(path.read_text(encoding="utf-8"))

    reports = []
    for claim in answer["claims"]:
        reports.append(audit_claim(claim, llm, tracer))

    for row in reports:
        print(row["verdict"], "-", row["reason"])
        print(" ", row["claim"]["text"])
        print()

    path = write_supported("titan_company", reports)
    print("memory saved:", path)
    