# Cost by question

Numbers come from `logs/qNN-analyst.jsonl` `run_end` events.
Memory is shared across the run. Caching a previous final answer does not happen.

| Q | ok | complete | tokens | ₹ | USD | seconds | memory facts used | queries skipped |
|---|----|----------|--------|---|-----|---------|-------------------|-----------------|
| Q01 | True | True | 5872 | 0.3712 | 0.003887 | 21.6 | 0 | 0 |
| Q02 | True | False | 14613 | 0.7386 | 0.007735 | 29.9 | 2 | 0 |
| Q03 | True | False | 8092 | 0.4327 | 0.004531 | 142.8 | 0 | 0 |
| Q04 | True | True | 7761 | 0.4301 | 0.004504 | 20.8 | 2 | 0 |
| Q05 | True | True | 9261 | 0.5908 | 0.006186 | 29.0 | 0 | 0 |
| Q06 | True | True | 6526 | 0.3945 | 0.004131 | 18.3 | 6 | 1 |
| Q07 | True | False | 11696 | 0.7265 | 0.007607 | 26.6 | 8 | 1 |
| Q08 | True | False | 5903 | 0.3397 | 0.003557 | 23.2 | 4 | 1 |

First scored question: Q01 ₹0.3712.
Last scored question: Q08 ₹0.3397 (8% vs first).
