import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { AnalysisRun, CaseMeta, SyntheticSettings } from "../api/types";
import { RunView } from "../components/RunView";
import { ErrorNotice } from "../components/Status";
import { EngineHeading } from "../components/EngineHeading";
import { describe } from "../lib/useAsync";

const ENGINES = ["PARE", "PARE_NO_RESIDUAL", "SHAP_IFOREST"];

/**
 * Build a small system, break one service, and see which explanations blame the
 * cause and which blame its callers (docs/04 section 3.5).
 */
export function LabPage() {
  const [settings, setSettings] = useState<SyntheticSettings>({
    nServices: 8,
    faultType: "LATENCY",
    rootService: null,
    propagation: 0.8,
    amplification: 0.25,
    noise: "MEDIUM",
    seed: 7,
  });
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [meta, setMeta] = useState<CaseMeta | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof SyntheticSettings>(key: K, value: SyntheticSettings[K]) =>
    setSettings((s) => ({ ...s, [key]: value }));

  const generate = async () => {
    setBusy(true);
    setError(null);
    setRuns([]);
    try {
      const summary = await api.synthetic(settings);
      const [detail, compared] = await Promise.all([
        api.caseDetail(summary.caseId),
        api.compare(summary.caseId, ENGINES, 0),
      ]);
      setMeta(detail.meta);
      setRuns(compared);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Synthetic lab</h1>
          <p>Generate a system with a known broken service, then see which explanation finds it.</p>
        </div>
      </div>
      <section className="panel stack">
        <div className="grid-3">
          <label className="field">
            Services: {settings.nServices}
            <input type="range" min={5} max={40} value={settings.nServices} onChange={(e) => set("nServices", Number(e.target.value))} />
          </label>
          <label className="field">
            How strongly a slow service slows its callers: {settings.propagation.toFixed(1)}
            <input type="range" min={0.2} max={1} step={0.1} value={settings.propagation} onChange={(e) => set("propagation", Number(e.target.value))} />
          </label>
          <label className="field">
            Amplification (callers overreact): {settings.amplification.toFixed(2)}
            <input type="range" min={0} max={2} step={0.05} value={settings.amplification} onChange={(e) => set("amplification", Number(e.target.value))} />
          </label>
          <label className="field">
            Fault
            <select value={settings.faultType} onChange={(e) => set("faultType", e.target.value as SyntheticSettings["faultType"])}>
              <option value="LATENCY">Latency (slow responses)</option>
              <option value="CPU">CPU</option>
              <option value="MEM">Memory leak</option>
              <option value="ERROR">Errors</option>
            </select>
          </label>
          <label className="field">
            Noise
            <select value={settings.noise} onChange={(e) => set("noise", e.target.value as SyntheticSettings["noise"])}>
              <option value="LOW">Low</option>
              <option value="MEDIUM">Medium</option>
              <option value="HIGH">High</option>
            </select>
          </label>
          <div className="row">
            <label className="field">
              Broken service
              <input
                placeholder="random, or e.g. svc-03"
                value={settings.rootService ?? ""}
                onChange={(e) => set("rootService", e.target.value.trim() || null)}
              />
            </label>
            <label className="field">
              Seed
              <input type="number" min={0} value={settings.seed} onChange={(e) => set("seed", Number(e.target.value))} style={{ width: 90 }} />
            </label>
          </div>
        </div>
        <div className="notice">
          Try increasing <strong>amplification</strong> and watch the ordinary methods start blaming the
          callers. Around 0.25 they begin to be fooled while PARE usually is not; by 0.5 PARE is fooled more
          often too.
          {settings.amplification > 0.7 && (
            <> Above about 0.7 the callers react so strongly that no method working from metrics alone can
            tell them from the cause. That is a limit of metric-only analysis, not something PARE fixes.</>
          )}
        </div>
        <div className="row">
          <button disabled={busy} onClick={generate}>
            {busy ? "Generating and analysing…" : "Generate and analyse"}
          </button>
          {meta && (
            <Link to={`/cases/${encodeURIComponent(meta.caseId)}`} className="small">
              Open this case on its own page
            </Link>
          )}
        </div>
      </section>
      <ErrorNotice message={error} />
      {meta && runs.length > 0 && (
        <div className="grid-3">
          {runs.map((run, i) => (
            <div key={run.runId}>
              <EngineHeading asked={ENGINES[i]} answered={run.engine} />
              <RunView run={run} meta={meta} showTruth compact />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
