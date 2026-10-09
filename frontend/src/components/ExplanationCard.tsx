import type { AnalysisRun } from "../api/types";
import { engineLabel } from "../lib/format";
import { api } from "../api/client";

/**
 * The plain-language answer. When the verdict is NO_CLEAR_CAUSE the card stays grey,
 * shows no cause sentences and no red: a quiet window must not look like an
 * accusation (docs/04 section 3.3).
 */
export function ExplanationCard({ run, showTruth = true }: { run: AnalysisRun; showTruth?: boolean }) {
  const found = run.response.verdict === "ROOT_CAUSE_FOUND";
  const e = run.explanation;
  return (
    <section className={`panel explanation ${found ? "cause-found" : "no-clear"}`} aria-label="Explanation">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="muted small">
          {engineLabel(run.engine)}, detection delay {run.delaySeconds} s, {run.tookMs} ms
        </span>
        <span className="row" style={{ gap: 6 }}>
          {found ? (
            <span className="badge neutral">confidence {e.confidence.toLowerCase()}</span>
          ) : (
            <span className="badge verdict-NO_CLEAR_CAUSE">no clear cause</span>
          )}
          {showTruth && run.evaluation && <TruthBadge run={run} />}
        </span>
      </div>
      <div className="headline">{e.headline}</div>
      <Sentences label="Why" items={e.causeSentences} />
      <Sentences label="Other services" items={e.symptomSentences} />
      <Sentences label="Timing" items={e.evidenceSentences} />
      <Sentences label="Notes" items={e.notes} />
      {showTruth && run.groundTruth && (
        <p className="small muted" style={{ marginTop: 8 }}>
          Known answer: <strong>{run.groundTruth.service}</strong>
          {run.groundTruth.indicator ? ` (${run.groundTruth.indicator})` : " (no single right metric for this fault)"}.
          The engine was never told it.
        </p>
      )}
      <a className="small" href={api.reportUrl(run.runId)} download>
        Download report (Markdown)
      </a>
    </section>
  );
}

function TruthBadge({ run }: { run: AnalysisRun }) {
  const ev = run.evaluation!;
  if (ev.correctTop1) {
    return <span className="badge correct">right service</span>;
  }
  return (
    <span className="badge wrong" title={ev.symptomError ? "It blamed a service that calls the real culprit" : undefined}>
      {ev.symptomError ? "blamed a symptom" : "wrong service"}
      {ev.rankGtService ? `, true cause ranked ${ev.rankGtService}` : ""}
    </span>
  );
}

function Sentences({ label, items }: { label: string; items: string[] }) {
  if (!items.length) {
    return null;
  }
  return (
    <>
      <div className="sentences-label">{label}</div>
      <ul>
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </>
  );
}
