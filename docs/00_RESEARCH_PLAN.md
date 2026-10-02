# Research Plan: Explainable Anomaly Detection and Root-Cause Analysis for Distributed Systems

MTech project plan, written with a research paper as the end goal.
Constraint: everything must run on a normal laptop CPU (no GPU training).

Prepared: October 2026

---

## 1. One-paragraph summary

Many tools can say "something is wrong" in a microservice system. Fewer can say "why", and almost nobody checks whether the "why" is actually correct. The usual approach is: train an anomaly detector, run SHAP on it, and call the top features the explanation. The problem is that SHAP explains the detector, not the failure. In a distributed system the loudest signals are usually downstream symptoms (for example, frontend latency), not the root cause (for example, a memory leak in a backend service). This project (a) measures, on a public benchmark with ground-truth root causes, how often standard anomaly explanations point at the real cause, and (b) proposes a lightweight, CPU-only method that separates "inherited" deviations from "self-originated" deviations using the service call graph, so that explanations point at causes instead of symptoms.

Working title for the paper:

**"Explaining Symptoms or Causes? Propagation-Aware, CPU-Only Explanations for Anomalies in Microservice Systems"**

Working name for the method: **PARE** (Propagation-Aware Residual Explanations).

---

## 2. What the latest research says (state of the art, 2024 to 2026)

### 2.1 Benchmarks now exist, and they have ground truth for explanations

- **RCAEval** (Pham et al., WWW 2025 companion / arXiv 2412.17015) is the main open benchmark. It has 735 failure cases from three microservice systems (Online Boutique, Sock Shop, Train Ticket), 11 fault types, and three datasets:
  - RE1: 375 cases, metrics only (CPU, MEM, DISK, DELAY, LOSS faults)
  - RE2: 270 cases, metrics + logs + traces
  - RE3: 90 cases, code-level faults, metrics + logs + traces
- Very important for us: every case is annotated with both the **root-cause service** and the **root-cause indicator** (the specific metric or log line that shows the cause). That second label is a ready-made ground truth for checking whether an explanation is correct.
- It ships with 15 reproducible baselines in a pip package (`RCAEval`), and they are mostly CPU methods.

### 2.2 Simple statistical methods are very strong, and complex methods often fail

- The ASE 2024 study "Root Cause Analysis for Microservices based on Causal Inference: How Far Are We?" evaluated 9 causal discovery methods and 21 RCA methods. Causal-graph methods (PC, FCI, RCD, CIRCA, CausalRCA) often struggle on larger systems.
- BARO (FSE 2024) uses Bayesian online change-point detection plus a robust, non-parametric scorer and beats most causal methods.
- A key weakness found in that line of work: when the anomaly-detection time is imprecise, simple RCA collapses. For example, NSigma on Online Boutique scores Avg@5 around 0.94 to 1.0 for CPU/MEM faults when the detection time is exact, but drops to around 0.16 to 0.24 when detection is 60 seconds late.
- A 2026 thesis from the same group (arXiv 2606.09942) points out that most studies treat detection and RCA separately and assume the anomaly is perfectly segmented. Whether RCA still works with an imperfect detector is largely unknown. **This is a gap we can use.**

### 2.3 Theory now supports "rank by anomaly score"

- Orchard et al., NeurIPS 2025, "Root Cause Analysis of Outliers with Missing Structural Knowledge": when the causal graph is unknown, choosing the variables with the highest anomaly scores as root causes is causally justified (in polytrees). When the graph is known, a simple traversal that follows "jumps" in anomaly scores along the graph has guarantees.
- Earlier work (Budhathoki et al., ICML 2022, implemented in DoWhy's `gcm` module) attributes anomalies to the causal mechanism that changed, but needs a full structural causal model and expensive Shapley computations.
- Takeaway: we do not need deep learning. Calibrated per-metric anomaly scores plus the service graph are a theoretically sound base.

### 2.4 Explainability in microservice anomaly detection is still immature

- GAL-MAD (arXiv 2504.00058, 2025) is a recent "explainable" microservice anomaly detector. It uses a Graph Attention + LSTM autoencoder (GPU-style deep model) and then SHAP to localize the faulty service. Observations:
  - The authors note that only a few works use post-hoc XAI for microservice RCA.
  - They had to hand-tune SHAP by multiplying some features' values by 4 to make localization work.
  - Localization was evaluated on only 10 instances per fault type, and it failed completely for low-bandwidth and out-of-order-packet faults.
  - Their own future work says SHAP needs to be interpreted "in the context of application architecture". **That is exactly what PARE does.**
- Soldani et al. (yRCA 2023; SPE 2025; DataMod 2025/LNCS 2026) do explainable RCA from logs using declarative (rule-based) reasoning, including incomplete logs. Good related work, but logs only and rule-based.
- A 2026 survey (Cluster Computing, 117 studies, 2012 to 2025) stresses that diagnosis must be reliable, explainable and consistent under noisy, incomplete telemetry.

### 2.5 Evaluating explanations is an open problem

- "Evaluating Anomaly Explanations Using Ground Truth" (MDPI AI, 2024) says evaluation methods that compare anomaly explanations against true causes are lacking, and builds a synthetic benchmark (digital circuits) to do it.
- Sepulveda et al. (Expert Systems with Applications, 2025) propose a SHAP-based stability measure for anomaly detection explanations.
- Nobody (that we found) has evaluated XAI explanations of anomaly detectors against **real** root-cause indicators in microservice failure data. RCAEval makes this possible.

### 2.6 LLM agents are popular but weak at RCA (and need expensive compute)

- OpenRCA (ICLR 2025): the best model with a specialized agent solved only about 11% of cases.
- OpenRCA 2.0 (arXiv 2606.27154, June 2026): across 11 frontier LLMs, exact root-cause recovery is only about 20.7%, and agents often get the right service with a wrong reasoning path ("ungrounded diagnosis").
- This supports our angle: grounded, verifiable explanations from cheap statistical ML are valuable. We can position PARE as "grounded evidence that an LLM or a human can trust", without using LLMs ourselves.

### 2.7 Classical ML is enough for logs too

- ICSE 2024, "Deep Learning or Classical Machine Learning? An Empirical Study on Log-Based Anomaly Detection": simple algorithms (KNN, SLFN) beat deep models in both accuracy and time on public log datasets.
- Ali et al. (TOSEM, 2024/2025): traditional supervised ML performs about as well as deep learning on log anomaly detection and is less sensitive to hyperparameters.
- This justifies the CPU-only design scientifically, not just as a hardware limitation.

---

## 3. The research gap (in plain words)

1. **Explanations are rarely checked against the real root cause.** Papers show SHAP heatmaps and a few examples. They do not measure, across hundreds of failures, whether the top explained feature is the actual root-cause indicator.
2. **Explanations confuse symptoms with causes.** A detector looks at all metrics together, so SHAP gives the most credit to the biggest deviations. In microservices the biggest deviations are often downstream effects of the real fault.
3. **Explanations and RCA break when detection is late or early.** RCA methods are usually evaluated with the perfect fault-injection time. Real detectors are late. The effect of this on explanation quality has not been studied.
4. **Most "explainable" methods are deep and GPU-heavy,** while recent evidence shows simple methods are competitive.

---

## 4. Contributions (the novelty)

Aim: at least one solid contribution is enough for a workshop or mid-tier conference; all three together target a good conference or a journal.

**C1. An empirical study: "Do anomaly explanations point to root causes?"** (lowest risk, publishable on its own)
Evaluate common detector + explainer pairs (Isolation Forest + TreeSHAP, ECOD's built-in per-dimension scores, robust z-score, PCA reconstruction error, KernelSHAP, LIME) on all RCAEval cases. Measure how often the top-k explained features include the ground-truth root-cause indicator, and how this changes with fault type, system size, and detection delay. As far as we found, this has not been done on real microservice failure data with indicator-level ground truth.

**C2. A method: PARE (Propagation-Aware Residual Explanations).**
A CPU-only pipeline that uses the call graph to split each metric's deviation into a part explained by its dependencies (inherited) and a part not explained (self-originated). Explanations and root-cause ranking are built from the self-originated part. It also re-anchors the analysis window using change-point detection, so it stays accurate when the detector is late.

**C3. A multi-criteria evaluation protocol for explanation quality in distributed systems.**
Grounding (matches ground truth), faithfulness (removing explained features removes the anomaly), stability (same explanation under small changes), compactness (few features), and robustness to detection delay. Released as an open, reusable script on top of RCAEval.

Honest framing of novelty: the "residual given parents" idea shares its spirit with causal mechanism-change RCA (Budhathoki et al. 2022; Orchard et al. 2025). Our novelty is (a) a lightweight, practical version that uses the observed call graph instead of a fitted full causal model and Shapley values, (b) combining it with change-point re-anchoring for late detection, and (c) the first large-scale, ground-truth evaluation of whether explanations identify causes or symptoms. State this clearly in the paper; reviewers respect honest positioning.

---

## 5. Research questions

- **RQ1 (Grounding):** How often do standard anomaly explanations (SHAP and others) rank the true root-cause indicator in their top-k features?
- **RQ2 (Symptom vs cause):** When explanations are wrong, do they point to downstream services (symptoms)? How often?
- **RQ3 (Method):** Does PARE improve root-cause service accuracy and indicator accuracy compared with SHAP-based localization and RCAEval baselines (NSigma, BARO, CIRCA, RCD, epsilon-Diagnosis, PC-PageRank, DoWhy anomaly attribution)?
- **RQ4 (Robustness):** How do explanation quality and RCA accuracy change when the detection time is shifted by 0, 30, 60, 120 seconds? Does change-point re-anchoring fix the drop?
- **RQ5 (Cost and usefulness):** What is the CPU runtime per incident? Do the generated explanations help a person find the root cause faster? (small user study, optional)

---

## 6. Proposed method: PARE, step by step

Input for each incident: multivariate time series per service (latency, error rate, request rate, CPU, memory, disk, network), a normal period before the incident, and the service call graph (extracted from traces when available).

### Step 1: Build the call graph

- From traces (RE2, RE3): an edge A -> B if service A calls service B. Count calls to get weights.
- When traces are missing (RE1): use the known architecture of the benchmark app (documented in its repo), or infer a rough graph from lagged correlations in normal data. Compare these options in an ablation.

### Step 2: Learn normal behaviour (CPU, seconds per case)

Two lightweight models, both trained only on the normal period:

1. **Marginal score** for each metric: robust z-score using median and MAD (median absolute deviation). This is the simple, strong baseline signal.
2. **Dependency-conditioned predictor** for each metric m of service s: a ridge regression (or a small LightGBM model) that predicts m from (a) its own recent lags and (b) the metrics of the services that s calls (its children in the call graph).
   - Residual = actual value minus predicted value.
   - Self-score = residual divided by the MAD of residuals in the normal period.
   - Intuition: if the frontend is slow only because cartservice is slow, the predictor sees cartservice's slowness and predicts a slow frontend, so the frontend's residual is small. Cartservice's own memory jump is not explained by anything it calls, so its residual is large.

### Step 3: Detect and calibrate

- System alarm when the largest self-score (or an Isolation Forest score over all features) crosses a threshold.
- Set the threshold with split conformal calibration on held-out normal data, which gives a controlled false-positive rate (for example, at most 1%) under standard assumptions. This is cheap and gives a principled number to report.

### Step 4: Re-anchor the time window (handles late detection)

- After an alarm, take the top-scoring metrics and run a change-point detector (PELT from the `ruptures` library, or Bayesian online change-point detection) on a look-back window.
- Use the estimated change point as the start of the "abnormal" window and recompute scores. This directly targets the drop that NSigma-style methods show when detection is late.

### Step 5: Rank root causes

- Service score = aggregate of the self-scores of its metrics (max, or mean of top-2).
- Optional traversal (inspired by Orchard et al. 2025): start at the service where the alarm fired and move to the child with the largest self-score while the score keeps increasing; the stopping node is the root-cause candidate.
- Output: ranked list of services and, inside the top service, a ranked list of metrics (indicators).

### Step 6: Generate the explanation

Two kinds of output, both template-based (no LLM needed):

1. **Cause explanation**: "cartservice is the most likely origin. Its memory usage rose 6.1 MADs above normal starting at 10:42:13. This rise is not explained by any service it depends on."
2. **Symptom explanation**: "frontend latency also rose (5.3 MADs), but about 85% of it is predicted by cartservice latency, so it is likely a downstream effect."
3. **Counterfactual** (optional): the smallest set of metrics that, if reset to their normal median, brings the anomaly score below the threshold.

The symptom vs cause split is the core message of the paper and is easy to show in figures.

### Why it fits a CPU

- Ridge regression and robust statistics: milliseconds per metric.
- Isolation Forest + TreeSHAP (exact, tree-based): fast on CPU; the `shap` library supports scikit-learn Isolation Forest directly.
- ECOD and COPOD from PyOD: parameter-free and give per-feature contributions natively.
- PELT change-point detection: fast on short windows.
- Expected cost: a few seconds per incident; the whole RCAEval benchmark should run in hours on a laptop. Log and trace files in RE2/RE3 are large (millions of lines), so process them in chunks and start with one system.

---

## 7. Data

| Dataset | Use | Notes |
|---|---|---|
| RCAEval RE1 (375 cases) | Main metric-based evaluation | Fastest to start with; metrics only |
| RCAEval RE2 (270 cases) | Graph from traces, log features | Large; use chunked reading |
| RCAEval RE3 (90 cases) | Code-level faults, logs and traces | Shows limits of metric-only explanations |
| RS-Anomic (RobotShop, GAL-MAD paper) | Direct comparison with GAL-MAD's SHAP localization | 12 services, 10 anomaly types; public on GitHub |
| Loghub (HDFS, BGL) | Optional log-event anomaly part | Drain3 log parsing + classical ML |
| Synthetic generator (ours) | Controlled study: vary graph size, propagation strength, noise | Shows when and why PARE helps |

Note the granularity asked in the project brief: request (trace-level), service (metric-level), event (log-level). The paper should focus on the service level (strongest ground truth). Request-level and event-level explanations can be shown in the application and as a smaller experiment on RE2/RE3.

---

## 8. Experiments

### 8.1 Baselines

- Detection + explanation: Isolation Forest + TreeSHAP, ECOD, robust z-score, PCA, KernelSHAP on an autoencoder (small, CPU), LIME.
- SHAP-based localization in the style of GAL-MAD (aggregate absolute SHAP per service, pick the max), but on a CPU model.
- RCA baselines from the `RCAEval` package: NSigma, BARO, epsilon-Diagnosis, CIRCA, RCD, PC-PageRank, MicroCause (run what works on CPU; document anything skipped).
- DoWhy `gcm` anomaly attribution (causal mechanism-based) on the call graph.

### 8.2 Metrics

Detection:
- Precision, recall, F1, false-positive rate, detection delay (seconds).

Root cause (as in RCAEval):
- AC@1, AC@3, Avg@5 for the root-cause service (coarse) and the root-cause indicator (fine).

Explanation quality (contribution C3):
- **Grounding**: ExpAC@k = fraction of cases where the ground-truth indicator is in the top-k explained features.
- **Symptom rate**: fraction of wrong top-1 explanations that point to a downstream service of the true root cause.
- **Faithfulness**: deletion test, i.e. replace the top-k explained features by their normal median and measure how much the anomaly score drops (area under the deletion curve).
- **Stability**: Jaccard overlap / Kendall tau of top-k features across random seeds, bootstrap samples of the normal period, and small window shifts.
- **Compactness**: number of features needed to reach 80% of the attribution mass.
- **Cost**: CPU seconds per incident, peak RAM.

### 8.2b Controlled synthetic study

Because the true cause and propagation are known exactly in synthetic data, vary graph size, propagation strength, noise, graph errors and detection delay one at a time. This shows when ordinary explanations start blaming symptoms and when PARE helps or fails. It is cheap (minutes on a laptop) and gives clear figures.

### 8.3 Ablations

- PARE without residuals (marginal scores only).
- PARE without change-point re-anchoring.
- Call graph from traces vs from architecture docs vs inferred from correlation vs no graph.
- Ridge vs LightGBM as the dependency predictor.
- Detection delay sweep: 0, 30, 60, 120 seconds.

### 8.4 Statistics

- Wilcoxon signed-rank test across cases for paired comparisons, Cliff's delta for effect size, and 95% bootstrap confidence intervals. Report per fault type and per system, not only averages.

### 8.5 Expected results (hypotheses, not promises)

- H1: Plain SHAP on a joint detector will often rank downstream latency metrics first, so ExpAC@1 for the true indicator will be noticeably lower than service-level accuracy.
- H2: PARE will improve indicator-level grounding and reduce the symptom rate, especially for resource faults (CPU, MEM, DISK) where propagation is strong.
- H3: Change-point re-anchoring will recover a large part of the accuracy lost under 60 to 120 second detection delay.
- H4: Network faults (packet loss, bandwidth) and code-level faults will remain hard for metric-only methods; logs/traces help there. Report this honestly as a limitation.

Note: PARE may not beat BARO on coarse service ranking. That is fine. The paper's main claims are about explanation grounding, symptom vs cause, and robustness to delay.

---

## 9. Minimum viable paper (safety net)

If the method gives only small gains, the paper still works as:

> "An Empirical Study of Explanation Grounding for Anomaly Detection in Microservice Systems"

with C1 + C3 as the main contributions and PARE as a simple, strong baseline. Empirical studies with clear findings ("explanations point at symptoms X% of the time") are publishable in software engineering venues.

---

## 10. The application (Java backend + React frontend + Python engine)

The project is delivered as a complete explainable-AI application, not only as research scripts. Java (Spring Boot) is required for the backend. No cloud or messaging tools are needed: no Kafka, Docker, Prometheus or Jaeger. The application runs on a laptop with three local processes. The React frontend is the user interface for the whole project.

1. **React frontend** (Vite): browse failure cases, play them back as if live, see the explanation, compare methods, run a synthetic lab, view benchmark accuracy.
2. **Spring Boot backend (Java)**: the REST API the frontend talks to. It owns the case catalog, the replay engine with a live (online) anomaly detector written in Java, the calls to the Python engine, a Java fallback ranker, the plain-language explanation text, storage of every analysis run (H2 file database), benchmark jobs and report export.
3. **Python engine (FastAPI)**: the PARE algorithm and baselines, also used by the offline paper experiments.

Data for the application comes from the RCAEval benchmark (exported to a simple uniform folder format) and from our synthetic generator. Users can also upload their own CSV with a call graph.

"Replay" mode replaces a live testbed: the backend feeds a recorded failure case row by row to the Java detector, so the audience sees normal behaviour, the alarm, and then the explanation, just like in production, but with known ground truth.

---

## 11. Tools and libraries (all CPU)

- Python: pandas, numpy, scikit-learn, PyOD (optional), shap, lightgbm, ruptures (change points), statsmodels, networkx, dowhy, FastAPI, RCAEval package.
- Java: Java 21, Spring Boot 3.x (web, validation, data-jpa), H2 database (file mode), springdoc-openapi.
- Frontend: React + Vite + TypeScript, Recharts (charts), React Flow (call graph).
- Hardware: laptop with 8 to 16 GB RAM. Process RE2/RE3 one system at a time.

---

## 12. Timeline (about 10 months)

| Month | Work | Output |
|---|---|---|
| 1 | Literature review (Section 14), install RCAEval, reproduce NSigma and BARO on RE1 Online Boutique | Reproduced baseline numbers |
| 2 | Build evaluation harness: detectors + explainers, ExpAC@k, symptom rate, delay sweep | C1 pipeline on RE1 |
| 3 | Run C1 on all RE1 systems; analyse results | First findings (RQ1, RQ2) |
| 4 | Implement PARE steps 1 to 5 | PARE on RE1 |
| 5 | Change-point re-anchoring, conformal threshold, ablations | RQ3, RQ4 results on RE1 |
| 6 | Extend to RE2/RE3 (traces for call graph, log features), RS-Anomic comparison | Full results tables |
| 7 | Spring Boot backend + Python engine service, synthetic controlled study | Backend API + E6 results |
| 8 | Explanation generator, faithfulness and stability metrics, optional user study | RQ5 |
| 9 | Write paper, make figures, release code | Paper draft |
| 10 | Internal review, revise, submit; write thesis | Submission + thesis |

Tip: aim to have a short-paper version (C1 alone) ready by month 4 or 5 in case a workshop deadline comes up.

---

## 13. Paper outline

1. Introduction: symptoms vs causes problem, one motivating example figure.
2. Background and related work: RCA for microservices (causal, statistical, LLM), XAI for anomaly detection, explanation evaluation.
3. Empirical study (C1): setup, RQ1 and RQ2 findings.
4. PARE method (C2).
5. Evaluation protocol (C3).
6. Results: RQ3 to RQ5, ablations, runtime.
7. Controlled synthetic study and the application (Java backend + React frontend).
8. Threats to validity: injected faults vs real incidents, benchmark size, single root cause assumption, call-graph quality.
9. Conclusion and released artifacts.

Possible venues (check current calls and deadlines yourself): software engineering and reliability conferences and their workshops (for example ISSRE, ICSE/FSE workshops, ISEC in India), cloud and services conferences (IEEE CLOUD, ICSOC), and journals such as Journal of Systems and Software, IEEE Access, or Cluster Computing.

---

## 14. Key references (start here)

Found in this literature search:

1. Pham et al. RCAEval: A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data. arXiv 2412.17015. Code: https://github.com/phamquiluan/RCAEval
2. Pham et al. Root Cause Analysis for Microservices based on Causal Inference: How Far Are We? ASE 2024. arXiv 2408.13729
3. Pham et al. BARO: Robust Root Cause Analysis for Microservices via Multivariate Bayesian Online Change Point Detection. FSE 2024. (Also the 2026 thesis: arXiv 2606.09942)
4. Orchard et al. Root Cause Analysis of Outliers with Missing Structural Knowledge. NeurIPS 2025. arXiv 2406.05014
5. Akmeemana et al. GAL-MAD: Towards Explainable Anomaly Detection in Microservice Applications Using Graph Attention Networks. arXiv 2504.00058 (RS-Anomic dataset: https://github.com/ms-anomaly/rs-anomic)
6. Soldani, Forti, Brogi. yRCA: An explainable failure root cause analyser. Science of Computer Programming, 2023.
7. Soldani et al. Explainable Root Cause Analysis for Microservices' Incomplete Logs. DataMod 2025, LNCS 16421, 2026.
8. Anomaly detection and root-cause identification in microservices: a survey. Cluster Computing, 2026.
9. Xu et al. OpenRCA: Can Large Language Models Locate the Root Cause of Software Failures? ICLR 2025.
10. Fang et al. OpenRCA 2.0: From Outcome Labels to Causal Process Supervision. arXiv 2606.27154, 2026.
11. Gopal and Krishnan. How Far Can Root Cause Analysis Go on Real-World Telemetry Data? arXiv 2607.13548, 2026.
12. Yu et al. Deep Learning or Classical Machine Learning? An Empirical Study on Log-Based Anomaly Detection. ICSE 2024.
13. Ali et al. A Comprehensive Study of Machine Learning Techniques for Log-Based Anomaly Detection. arXiv 2307.16714.
14. Evaluating Anomaly Explanations Using Ground Truth. AI (MDPI), vol. 5(4), 2024.
15. Sepulveda et al. Enhancing explainability in real-world scenarios: towards a robust stability measure for local interpretability. Expert Systems with Applications, 2025.
16. Xin et al. CausalRCA. Journal of Systems and Software, 2023.

Well-known foundations (from general knowledge; verify exact details before citing):

17. Budhathoki et al. Causal structure-based root cause analysis of outliers. ICML 2022 (implemented in DoWhy gcm).
18. Lundberg and Lee. A Unified Approach to Interpreting Model Predictions (SHAP). NeurIPS 2017; Lundberg et al. TreeSHAP, Nature Machine Intelligence 2020.
19. Liu, Ting, Zhou. Isolation Forest. ICDM 2008.
20. Li et al. ECOD: Unsupervised Outlier Detection Using Empirical Cumulative Distribution Functions. IEEE TKDE 2022.
21. Killick, Fearnhead, Eckley. Optimal detection of changepoints with a linear computational cost (PELT). JASA 2012.
22. Bates et al. Testing for outliers with conformal p-values. Annals of Statistics 2023.
23. He et al. Drain: An online log parsing approach with fixed depth tree. ICWS 2017.

---

## 15. Risks and how to handle them

| Risk | Mitigation |
|---|---|
| PARE does not beat BARO on service ranking | Focus claims on indicator grounding, symptom rate and delay robustness; fall back to the empirical-study paper (Section 9) |
| RE2/RE3 files too big for the laptop | Start with RE1; stream logs/traces in chunks; one system at a time |
| Call graph missing for RE1 | Use the documented architecture of the benchmark apps; ablate with an inferred graph |
| Someone publishes a very similar idea | Search arXiv monthly for "explainable root cause microservices", "SHAP root cause", "RCAEval"; your evaluation (C1 and C3) stays useful even if a similar method appears |
| Application takes too long | Build the backend API first, then a minimal frontend; the paper does not depend on the UI |
| Multiple simultaneous root causes | State the single-root-cause assumption clearly as a limitation |

---

## 16. First two weeks: concrete checklist

1. `pip install RCAEval` and download RE1 (Online Boutique first).
2. Reproduce NSigma and BARO numbers, including the delayed-detection setting.
3. Read papers 1, 2, 4 and 5 fully.
4. Write a 40-line script: Isolation Forest + TreeSHAP on one RE1 case, print top-5 features, compare with the ground-truth indicator. This single result tells you quickly whether the symptom vs cause story holds.
5. Draft the motivating example figure for the paper from that case.
