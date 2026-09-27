## 1. What I optimized for

The Final answer is not a LLM generated Essay, its a DETERMINISTIC PYTHON GATE, the gate only shows supported claims.
Only Auditor supported Claims are stored as a Fact: { entity, field, text, ...} in the memory.

## 2. Decisions I will defend

i. Python gate, not an LLM final essay. The model already wants to sound finished. Completeness would become tone. A free-write at the end would let rejected claims sneak back in, which kind of dismisses the whole purpose
The gate only shows SUPPORTED claims. 

ii. Plans are not claims. Jewellery headlines are “will open.” Analyst is not allowed will / plans. That is why Q03 has zero supported claims.

## 3. Obvious approach, measured, rejected

i. One-shot vs the loop on Q01


|        | Naive Q01                   | Loop Q01                    |
| ------ | --------------------------- | --------------------------- |
| Answer | C.K. Venkataraman, Oct 2020 | Ajoy Chawla, 1 Jan 2026     |
| Cost   | ₹0.02, 3s                   | ₹0.37, 22s                  |
| Tools  | none                        | search, fetch, quote, audit |


I rejected one-shot because it is cheap and a year out of date. I pay ~15× to not ship 2020 as 2026.

Q03: both empty. Naive: knowledge cutoff. Loop: no quoted “opened.” I prefer the research-based honesty.

ii. Earlier architecture

I restarted because two design choices were wrong
.We chopped every page (download cap, then another 3000 characters), so the MD line could sit on the page and the model still said not_found. We also never specified entities and required fields first, so claims wandered off the question. Fetching only the first three URLs made that worse. 
Cursor suggest some patches.
###BUT I STARTED OVER

## 4. Weaknesses I found

i. Q03 has 0 claims, 143s.
The question asked for retailers that already opened stores in 2025, with a count. Search mostly returned “Malabar plans to open…”, “ICRA projects additions.” Analyst is not allowed will / plans as claims. So it wrote three unanswered rows and no claims. Wave 2 still ran (leftover URLs), so we paid extra time (143s, others ~20–30s) and still got nothing.

ii. Cost did not fall by half.
The cost fluctuated. I did claim memory would cut the cost, and a skip fired once on Q06, Q07, and Q08 (queries skipped = 1). It did not cut the bill much. Q01 ₹0.37 → Q08 ₹0.34 (8%). 

iii. Auditor all SUPPORTED.
Analyst already drops unquoted drafts. It only emits a claim if the quote is on the passage. Bad drafts never reach the auditor. This table does not prove the auditor is strict. I have not shown a live CONTRADICTED on this locked set.

iv. Q08 skip was too eager Q08 asked two things: is Ajoy still MD? Cite a page. And name a brand.

Memory already had “Ajoy is MD.” The planner skipped the MD search. Fetch then followed brand links (Tanishq). Analyst found Tanishq and left MD + citation missing. Completeness failed on the verify half — the part reuse was supposed to prove with a fresh page.

## 5. What I would not do again / what still matters

#### A cross-check misread must not veto a SUPPORTED claim. 
First eval: Analyst + Auditor had 1 Jan 2026. Cross-check (or a misread page) said 2024. The gate hid the date and left it out of the final answer. A second page should not beat a citation the auditor already backed.

#### Cross-check query by tokens
Fix: search with Ajoy, 472, 2026, not the whole sentence; drop the page if it does not share those words.
