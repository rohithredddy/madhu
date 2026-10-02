# 01 - Project Overview (plain language)

## The problem

A modern app is often split into many small services (microservices) that call each other. When one service breaks, others that depend on it also look broken. For example, if the payment service runs out of memory and gets slow, the order service and the gateway also get slow because they wait for payment.

Monitoring tools can say "something is wrong". Some can also say "these numbers look strange". But they usually show the loudest strange numbers, and the loudest ones are often the victims, not the culprit. Engineers then waste time looking at the wrong service.

## What we build

1. **PARE**, a small CPU-only algorithm. For every service, it learns from normal data how the service's numbers depend on the services it calls. When an incident happens, it asks: "how much of this service's strange behaviour is explained by the services it calls?" The part that is NOT explained belongs to the service itself. The service with the biggest unexplained part is the likely root cause.
2. **A way to measure whether explanations are correct**, using a public benchmark (RCAEval) where the true root cause of every failure is known.
3. **A complete explainable-AI application** (the final project deliverable): a React web page talks to a Java Spring Boot backend, which calls the Python engine. You can pick a real recorded failure, play it back as if it were happening live, watch the Java detector raise an alarm, and read a plain explanation of which service caused it and which were only affected. A "synthetic lab" lets you build a fake system, break one service, and see when ordinary explanations go wrong and PARE does not.

## What success looks like

- Paper: tables showing how often normal explanations point to the wrong service, and that PARE points to the right one more often, also when detection is late.
- Application: a user picks a recorded failure (for example a memory fault in cartservice), presses Play, sees the alarm, and the page says "cartservice is the likely cause; frontend and checkoutservice are only affected", with a chart that shows why. The ground truth is shown next to it.

## Glossary

| Word | Meaning |
|---|---|
| Microservice | A small independent program that does one job and talks to others over the network |
| Anomaly | Behaviour that is different from normal |
| Root cause | The service (and metric) where the problem really started |
| Symptom | A service that looks bad only because something it depends on is bad |
| Root-cause indicator | The specific metric or log that shows the root cause, e.g. `payment-service memory` |
| Call graph | Who calls whom. Edge A -> B means A calls B |
| Metric | A number measured over time, e.g. latency, CPU, memory, error rate |
| Trace | The record of one request travelling through several services |
| Robust z-score | How far a value is from normal, using median and MAD instead of mean and standard deviation, so outliers in training do not spoil it |
| MAD | Median absolute deviation, a robust measure of spread |
| Residual | Actual value minus predicted value |
| Self-score | Robust z-score of the residual; how unusual a service is after removing what its dependencies explain |
| Change point | The moment a time series changes behaviour |
| SHAP | A popular method that says how much each input feature pushed a model's output |
| Conformal threshold | A way to choose an alarm threshold from normal data so false alarms stay below a chosen rate |
| RCAEval | Public benchmark with 735 labelled microservice failures |
| Replay | Playing a recorded failure row by row so it looks live |
| Case | One recorded or synthetic failure in our simple folder format: data.csv + meta.json |
| AC@k | Fraction of cases where the true root cause is in the top k answers |
| Avg@5 | Average of AC@1 to AC@5 |
| ExpAC@k | Our metric: fraction of cases where the true root-cause indicator is in the top k explained features |
| Symptom rate | Our metric: among wrong top-1 answers, the fraction that pointed at a service that calls the true root cause directly or indirectly (so it was affected by it) |
| Ancestor (in call graph) | A service that calls another service directly or through others. Faults travel from a called service up to its ancestors |
