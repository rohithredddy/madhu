import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { causeSymptomRows } from "./components/CauseSymptomChart";
import { ExplanationCard } from "./components/ExplanationCard";
import { rescale } from "./components/SeriesChart";
import type { AnalysisRun, ServiceRanking } from "./api/types";
import { layoutGraph } from "./lib/graphLayout";

const svc = (service: string, score: number, marginal: number, role: ServiceRanking["role"]): ServiceRanking => ({
  service,
  rank: 0,
  score,
  marginalScore: marginal,
  inheritedFraction: role === "SYMPTOM" ? 0.8 : 0,
  topIndicator: `${service}_latency`,
  role,
  explainedBy: null,
});

describe("cause versus symptom chart data", () => {
  it("keeps each service's own and marginal score and sorts by the own score", () => {
    const rows = causeSymptomRows([
      svc("front", 1.4, 8.3, "SYMPTOM"),
      svc("cart", 11.2, 11.9, "CAUSE"),
      svc("pay", 4.0, 4.0, "ALSO_ABNORMAL"),
    ]);
    expect(rows.map((r) => r.service)).toEqual(["cart", "pay", "front"]);
    // A symptom: looks unusual (8.3) but little of it is its own (1.4).
    expect(rows[2]).toMatchObject({ marginal: 8.3, self: 1.4, role: "SYMPTOM" });
  });

  it("shows a missing score as zero height, never inventing one", () => {
    const rows = causeSymptomRows([{ ...svc("x", 0, 0, "NORMAL"), score: null, marginalScore: null }]);
    expect(rows[0]).toMatchObject({ marginal: 0, self: 0 });
  });

  it("cuts to the limit", () => {
    const many = Array.from({ length: 12 }, (_, i) => svc(`s${i}`, i, i, "NORMAL"));
    expect(causeSymptomRows(many, 8)).toHaveLength(8);
  });
});

describe("call graph layout", () => {
  it("puts callers above the services they call", () => {
    const placed = layoutGraph(["front", "cart", "db", "lonely"], [
      { from: "front", to: "cart" },
      { from: "cart", to: "db" },
    ]);
    const layer = Object.fromEntries(placed.map((p) => [p.id, p.layer]));
    expect(layer.front).toBeLessThan(layer.cart);
    expect(layer.cart).toBeLessThan(layer.db);
    // A service with no edges still appears, below the graph.
    expect(layer.lonely).toBeGreaterThan(layer.db);
  });

  it("survives a cycle", () => {
    const placed = layoutGraph(["a", "b"], [
      { from: "a", to: "b" },
      { from: "b", to: "a" },
    ]);
    expect(placed).toHaveLength(2);
  });
});

describe("series rescaling", () => {
  it("maps to 0..1 and keeps missing readings missing", () => {
    expect(rescale([2, null, 4, 3])).toEqual([0, null, 1, 0.5]);
    expect(rescale([null, null])).toEqual([null, null]);
  });
});

describe("explanation card", () => {
  const base: AnalysisRun = {
    runId: "r1",
    caseId: "c",
    engine: "PARE",
    mode: "ONE_CLICK",
    delaySeconds: 0,
    createdAt: "2026-10-09T00:00:00Z",
    tookMs: 10,
    response: {
      requestId: null,
      engine: "PARE",
      engineVersion: "0.1.0",
      tookMs: 10,
      verdict: "NO_CLEAR_CAUSE",
      alarmTimeSec: 0,
      changePointSec: null,
      windowStartSec: 0,
      windowEndSec: 0,
      services: [svc("cart", 2.1, 2.1, "NORMAL")],
      indicators: [],
      warnings: [],
    },
    explanation: {
      headline: "No clear root cause found. The strongest signal is cart (2.1).",
      confidence: "LOW",
      causeSentences: [],
      symptomSentences: [],
      evidenceSentences: ["Alarm at 00:00:00 UTC."],
      notes: [],
    },
    groundTruth: { service: "cart", indicator: "cart_mem" },
    evaluation: { rankGtService: 1, rankGtIndicator: null, correctTop1: true, correctTop3: true, symptomError: false },
  };

  it("never looks like an accusation when there is no clear cause", () => {
    const { container, getByText } = render(<ExplanationCard run={base} />);
    expect(getByText(/No clear root cause found/)).toBeTruthy();
    expect(container.querySelector(".explanation.no-clear")).not.toBeNull();
    expect(container.querySelector(".explanation.cause-found")).toBeNull();
    expect(container.querySelector(".role-CAUSE")).toBeNull();
    expect(container.textContent).not.toContain("Why");
  });

  it("hides the known answer when asked", () => {
    const { container } = render(<ExplanationCard run={base} showTruth={false} />);
    expect(container.textContent).not.toContain("Known answer");
    expect(container.textContent).not.toContain("right service");
  });
});
