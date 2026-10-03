# Cost by question

Numbers come from `logs/qNN-analyst.jsonl` `run_end` events.
Memory is shared across the run. Caching a previous final answer does not happen.

| Q | ok | complete | tokens | ₹ | USD | seconds | memory facts used | queries skipped |
|---|----|----------|--------|---|-----|---------|-------------------|-----------------|
| Q01 | True | True | 5786 | 0.3521 | 0.003687 | 22.1 | 0 | 0 |
| Q02 | True | False | 9871 | 0.4721 | 0.004943 | 150.7 | 0 | 0 |
| Q03 | True | True | 14055 | 0.7544 | 0.007899 | 24.8 | 0 | 0 |
| Q04 | True | True | 7615 | 0.4279 | 0.004480 | 18.5 | 1 | 1 |
| Q05 | True | True | 9025 | 0.4840 | 0.005068 | 30.1 | 0 | 0 |
| Q06 | True | True | 2574 | 0.1851 | 0.001938 | 7.8 | 4 | 0 |
| Q07 | True | False | 17996 | 1.0889 | 0.011403 | 43.2 | 4 | 0 |
| Q08 | True | True | 5650 | 0.3014 | 0.003156 | 11.5 | 8 | 0 |
| Q09 | True | False | 11987 | 0.5121 | 0.005363 | 27.5 | 8 | 0 |

Memory pair: cold Q01 ₹0.3521 → verify Q06 ₹0.1851 (−47%).
