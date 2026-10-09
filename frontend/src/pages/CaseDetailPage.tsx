import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { AnalysisRun, CaseDetail } from "../api/types";
import { DelaySlider, EngineSelect } from "../components/Controls";
import { EngineHeading } from "../components/EngineHeading";
import { RunView } from "../components/RunView";
import { SeriesChart, type Marker } from "../components/SeriesChart";
import { ErrorNotice, Loading } from "../components/Status";
import { cssVar } from "../lib/colors";
import { engineLabel } from "../lib/format";
import { describe, useAsync } from "../lib/useAsync";

const COMPARE = ["PARE", "SHAP_IFOREST", "NSIGMA"];

/** One failure: analyse it with one engine, or compare three (docs/04 section 3.3). */
export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const detail = useAsync(() => api.caseDetail(caseId), [caseId]);
  const engines = useAsync(() => api.engines(), []);
  const [engine, setEngine] = useState("PARE");
  const [delay, setDelay] = useState(0);
  const [showTruth, setShowTruth] = useState(true);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async (action: () => Promise<AnalysisRun[]>) => {
    setBusy(true);
    setError(null);
    try {
      setRuns(await action());
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  if (detail.loading && !detail.data) {
    return <Loading what="Loading the failure" />;
  }
  if (detail.error || !detail.data) {
    return <ErrorNotice message={detail.error ?? "Not found"} />;
  }
  const d = detail.data;
  const truth = d.meta.groundTruth;
  const available = (engines.data ?? []).filter((e) => e.available);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>{d.meta.caseId}</h1>
          <p>
            {d.meta.system}, {d.meta.faultType} fault, {d.summary.nRows} rows of {d.summary.nColumns} metrics
            {showTruth && truth ? `. Broken service: ${truth.service}` : ""}
            {showTruth && truth?.indicator ? ` (${truth.indicator})` : ""}.
          </p>
        </div>
        <label className="row small">
          <input type="checkbox" checked={!showTruth} onChange={(e) => setShowTruth(!e.target.checked)} />
          Hide the answer
        </label>
      </div>

      <section className="panel row" style={{ alignItems: "flex-end" }}>
        {available.length > 0 && <EngineSelect engines={available} value={engine} onChange={setEngine} />}
        <div style={{ minWidth: 220 }}>
          <DelaySlider value={delay} onChange={setDelay} />
        </div>
        <button disabled={busy} onClick={() => go(async () => [await api.analyze(caseId, engine, delay)])}>
          {busy ? "Analysing…" : "Analyze"}
        </button>
        <button className="secondary" disabled={busy} onClick={() => go(() => api.compare(caseId, COMPARE, delay))}>
          Compare {COMPARE.map(engineLabel).join(", ")}
        </button>
      </section>
      <ErrorNotice message={error ?? engines.error} />

      {runs.length === 0 && !busy && (
        <p className="muted">
          Choose an engine and a detection delay, then analyse. The delay simulates a detector that raised
          the alarm late.
        </p>
      )}
      {runs.length === 1 && (
        <>
          <RunView run={runs[0]} meta={d.meta} showTruth={showTruth} />
          <Series detail={d} run={runs[0]} showTruth={showTruth} />
        </>
      )}
      {runs.length > 1 && (
        <div className="grid-3">
          {runs.map((run, i) => (
            <div key={run.runId}>
              <EngineHeading asked={COMPARE[i]} answered={run.engine} />
              <RunView run={run} meta={d.meta} showTruth={showTruth} compact />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The top three metrics and the true one, around the incident, with markers. */
function Series({ detail, run, showTruth }: { detail: CaseDetail; run: AnalysisRun; showTruth: boolean }) {
  const columns = Array.from(
    new Set([
      ...run.response.indicators.slice(0, 3).map((i) => i.column),
      ...(showTruth && detail.meta.groundTruth?.indicator ? [detail.meta.groundTruth.indicator] : []),
    ]),
  );
  const inject = detail.meta.injectTimeSec;
  const alarm = run.response.alarmTimeSec ?? inject;
  const series = useAsync(
    () => api.series(detail.meta.caseId, columns, 600, inject - 600, alarm + 240),
    [detail.meta.caseId, columns.join(","), inject, alarm],
  );
  // With no delay the alarm and the injection are the same moment: one marker, one
  // label, rather than two labels printed on top of each other.
  const together = showTruth && alarm === inject;
  const markers: Marker[] = [
    { time: alarm, label: together ? "alarm = fault injected" : "alarm", color: cssVar("--accent") },
  ];
  if (run.response.changePointSec !== null) {
    markers.push({ time: run.response.changePointSec, label: "change starts", color: cssVar("--ink-2") });
  }
  if (showTruth && !together) {
    markers.push({ time: inject, label: "fault injected", color: cssVar("--truth") });
  }
  return (
    <section className="panel">
      <h3>Over time</h3>
      <p className="small muted">Each line is scaled to its own range; hover for real values.</p>
      <ErrorNotice message={series.error} />
      {series.data && <SeriesChart timeSec={series.data.timeSec} series={series.data.series} markers={markers} />}
    </section>
  );
}
