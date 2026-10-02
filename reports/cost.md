# Cost by question

Numbers come from `logs/qNN-analyst.jsonl` `run_end` events.
Memory is shared across the run. Caching a previous final answer does not happen.

| Q | ok | complete | tokens | ₹ | USD | seconds | memory facts used | queries skipped |
|---|----|----------|--------|---|-----|---------|-------------------|-----------------|
| Q01 | True | True | 5786 | 0.3521 | 0.003687 | 22.1 | 0 | 0 |
| Q02 | True | True | 9425 | 0.4646 | 0.004865 | 21.6 | 3 | 1 |
| Q03 | True | True | 14634 | 0.8435 | 0.008832 | 30.2 | 0 | 0 |
| Q04 | True | True | 7615 | 0.4279 | 0.004480 | 18.5 | 1 | 1 |
| Q05 | True | True | 13245 | 0.7700 | 0.008063 | 40.1 | 0 | 0 |
| Q06 | True | True | 2574 | 0.1851 | 0.001938 | 7.8 | 4 | 0 |
| Q07 | True | False | 17996 | 1.0889 | 0.011403 | 43.2 | 4 | 0 |
| Q08 | True | True | 5650 | 0.3014 | 0.003156 | 11.5 | 8 | 0 |
| Q09 | True | False | 7549 | 0.3373 | 0.003532 | 18.7 | 3 | 0 |

First scored question: Q01 ₹0.3521.
Last scored question: Q09 ₹0.3373 (4% vs first).
