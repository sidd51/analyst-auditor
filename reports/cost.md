# Cost by question

Numbers come from `logs/qNN-analyst.jsonl` `run_end` events.
Memory is shared across the run. Caching a previous final answer does not happen.

| Q | ok | complete | tokens | ₹ | USD | seconds | memory facts used | queries skipped |
|---|----|----------|--------|---|-----|---------|-------------------|-----------------|
| Q01 | True | True | 5173 | 0.3524 | 0.003690 | 25.9 | 0 | 0 |
| Q02 | True | True | 14182 | 0.8614 | 0.009020 | 167.0 | 2 | 0 |
| Q03 | True | False | 7822 | 0.3876 | 0.004058 | 20.5 | 0 | 0 |
| Q04 | True | True | 7919 | 0.4288 | 0.004490 | 21.5 | 3 | 0 |
| Q05 | True | True | 10839 | 0.5929 | 0.006208 | 24.6 | 0 | 0 |
| Q06 | True | True | 3051 | 0.1994 | 0.002088 | 7.9 | 3 | 0 |
| Q07 | True | False | 3909 | 0.2517 | 0.002636 | 47.3 | 6 | 0 |
| Q08 | True | True | 9356 | 0.5813 | 0.006087 | 24.9 | 5 | 0 |
| Q09 | True | False | 4022 | 0.2215 | 0.002320 | 50.4 | 8 | 0 |

First scored question: Q01 ₹0.3524.
Last scored question: Q09 ₹0.2215 (37% vs first).
