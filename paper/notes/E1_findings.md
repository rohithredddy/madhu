# E1 findings - do anomaly explanations point at root causes? (RQ1, RQ2)

Source: `experiments/results/e1_re1/` (pooled from `e1_re1_ob`, `e1_re1_ss`, `e1_re1_tt`), RCAEval RE1, 375 cases, delay 0 s, 0 failed runs. Tables: `paper/tables/table2_e1_grounding.md`, `table2b_e1_loose.md`; figure: `paper/figures/fig3_e1_symptom_rate_by_fault.png`.

1. Explanations name the right service far more often than the right metric. On the same 150 CPU and MEM cases, Isolation Forest + TreeSHAP gets the service right 0.667 of the time and the metric right 0.100 (ExpAC@1), a gap of 0.567.
2. No method names the right metric even half the time at rank 1: ExpAC@1 is 0.353 for PCA reconstruction, 0.160 for robust z, 0.105 for ECDF and 0.100 for TreeSHAP over all of RE1.
3. The popular choice is not the best explainer: PCA reconstruction beats TreeSHAP on ExpAC@1 (0.353 vs 0.100) and on service AC@1 (0.667 vs 0.549), at 146 ms per case against 3564 ms.
4. When TreeSHAP is wrong, it blames a service that calls the real culprit in 0.651 of its wrong answers (86 judged), against 0.145 for a wrong answer picked at random - about 4.5 times chance.
5. That pattern holds on both systems with a call graph: TreeSHAP's symptom rate is 0.636 on Online Boutique (chance 0.161) and 0.667 on Sock Shop (chance 0.129).
6. It is worst on network delay: TreeSHAP's symptom rate is 0.862 on DELAY faults (29 judged) and 0.692 on MEM (13 judged), against 0.400 on CPU (10 judged).
7. The simple scorers sit much closer to chance: ECDF 0.192 (chance 0.132) and robust z 0.184 (chance 0.131) - their errors are mostly not symptom errors, though they are wrong far more often (AC@1 0.135 and 0.325).
8. PCA reconstruction's pooled symptom rate is 0.366 over 71 judged wrong answers, but its per-fault rates rest on few errors (4 wrong on DELAY), so only the pooled number should be quoted.
9. The metric gap is system-dependent: on Sock Shop TreeSHAP's ExpAC@1 is 0.020 while its service AC@1 is 0.664, and on Train Ticket PCA reconstruction reaches ExpAC@1 0.600.
10. Limits: Train Ticket has no call graph yet, so every symptom rate covers Online Boutique and Sock Shop only (250 cases); ExpAC@k is strict (CPU and MEM only); ties are scored as expected values under a random order.
