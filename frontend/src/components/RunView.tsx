import type { AnalysisRun, CaseMeta } from "../api/types";
import { CallGraphView } from "./CallGraphView";
import { CauseSymptomChart } from "./CauseSymptomChart";
import { ExplanationCard } from "./ExplanationCard";
import { IndicatorTable } from "./IndicatorTable";

/**
 * One analysis, shown the same way everywhere: the explanation, the call graph
 * coloured by role, and the cause-versus-symptom chart. `compact` drops the
 * indicator table, for side-by-side comparisons.
 */
export function RunView({
  run,
  meta,
  showTruth,
  compact = false,
}: {
  run: AnalysisRun;
  meta: CaseMeta;
  showTruth: boolean;
  compact?: boolean;
}) {
  const services = Array.from(new Set(meta.columns.map((c) => c.service)));
  // NO_CLEAR_CAUSE: nobody is CAUSE in the response, so no node is red (docs/04).
  return (
    <div className="stack">
      <ExplanationCard run={run} showTruth={showTruth} />
      <section className="panel">
        <h3>Call graph</h3>
        <CallGraphView
          graph={meta.graph}
          services={services}
          ranking={run.response.services}
          truthService={showTruth ? meta.groundTruth?.service : null}
        />
      </section>
      <section className="panel">
        <h3>Cause or symptom</h3>
        <p className="small muted">
          Grey: how unusual each service looks. Coloured: how much of it is its own problem once the
          services it calls are accounted for. A tall grey bar beside a short coloured one is a symptom.
        </p>
        <CauseSymptomChart services={run.response.services} />
      </section>
      {!compact && (
        <section className="panel">
          <h3>Metrics, most unusual first</h3>
          <IndicatorTable indicators={run.response.indicators} truth={showTruth ? meta.groundTruth?.indicator : null} />
        </section>
      )}
    </div>
  );
}
