import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { ReplayPhase, ReplayState } from "../api/types";
import { CauseSymptomChart } from "../components/CauseSymptomChart";
import { EngineSelect, ProgressBar } from "../components/Controls";
import { ExplanationCard } from "../components/ExplanationCard";
import { SeriesChart } from "../components/SeriesChart";
import { ErrorNotice, Loading } from "../components/Status";
import { cssVar } from "../lib/colors";
import { clock, one } from "../lib/format";
import { describe, useAsync } from "../lib/useAsync";

const SPEEDS = [1, 5, 20, 50];
const STEPS: ReplayPhase[] = ["LEARNING", "WATCHING", "ALARM", "EXPLAINED"];
const STEP_LABELS: Record<string, string> = {
  LEARNING: "Learning normal",
  WATCHING: "Watching",
  ALARM: "Alarm",
  EXPLAINED: "Explained",
};

/**
 * Plays a recorded failure as if it were live (docs/04 section 3.4). The Java detector
 * learns what normal looks like from the first rows, never knowing when the fault
 * will come, raises the alarm, and the analysis runs on the rows seen so far.
 */
export function ReplayPage() {
  const cases = useAsync(() => api.cases({ size: 1000 }), []);
  const engines = useAsync(() => api.engines(), []);
  const [caseId, setCaseId] = useState("");
  const [filter, setFilter] = useState("");
  const [speed, setSpeed] = useState(20);
  const [engine, setEngine] = useState("PARE");
  const [showTruth, setShowTruth] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [state, setState] = useState<ReplayState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const truthRef = useRef(showTruth);
  truthRef.current = showTruth;

  // Recorded failures first: generated cases have drifting load and a random-walk
  // memory metric, which make the live detector alarm early on them (decision 83).
  const replayable = useMemo(
    () =>
      (cases.data?.items ?? [])
        .filter((c) => c.replayable && c.caseId.toLowerCase().includes(filter.toLowerCase()))
        .sort((a, b) => Number(a.source === "SYNTHETIC") - Number(b.source === "SYNTHETIC") || a.caseId.localeCompare(b.caseId)),
    [cases.data, filter],
  );

  // Poll once a second while a session is live.
  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let alive = true;
    let failures = 0;
    let timer: ReturnType<typeof setInterval> | undefined;
    const poll = async () => {
      try {
        const next = await api.replay(sessionId, truthRef.current);
        failures = 0;
        if (alive) {
          setState(next);
          // Nothing more will change once the replay has ended: stop asking.
          if (["EXPLAINED", "FINISHED", "STOPPED"].includes(next.state)) {
            clearInterval(timer);
          }
        }
      } catch (e) {
        failures += 1;
        // Three misses in a row: the backend went away (or forgot the session after
        // a restart). Stop polling and say so, rather than retrying every second.
        if (alive && failures >= 3) {
          clearInterval(timer);
          setError(`Lost contact with the replay: ${describe(e)}`);
        }
      }
    };
    poll();
    timer = setInterval(poll, 1000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [sessionId]);

  const start = async () => {
    setError(null);
    setState(null);
    try {
      const { sessionId } = await api.startReplay(caseId, speed, engine);
      setSessionId(sessionId);
    } catch (e) {
      setError(describe(e));
    }
  };

  const stop = async () => {
    if (sessionId) {
      await api.stopReplay(sessionId).catch(() => undefined);
    }
  };

  const live = state && !["EXPLAINED", "FINISHED", "STOPPED"].includes(state.state);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Replay</h1>
          <p>Play a recorded failure row by row, as if it were happening now.</p>
        </div>
      </div>
      <section className="panel row" style={{ alignItems: "flex-end" }}>
        <label className="field" style={{ minWidth: 280, flex: 1 }}>
          Failure ({replayable.length} can be replayed)
          <input aria-label="Filter failures" placeholder="Filter, e.g. cartservice" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <select aria-label="Failure to replay" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
            <option value="">Choose a failure…</option>
            {replayable.map((c) => (
              <option key={c.caseId} value={c.caseId}>
                {c.caseId}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          Speed
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s} rows per second
              </option>
            ))}
          </select>
        </label>
        {engines.data && (
          <EngineSelect engines={engines.data.filter((e) => e.available)} value={engine} onChange={setEngine} />
        )}
        <button disabled={!caseId || !!live} onClick={start}>
          Play
        </button>
        <button className="secondary" disabled={!live} onClick={stop}>
          Stop
        </button>
        <label className="row small">
          <input type="checkbox" checked={showTruth} onChange={(e) => setShowTruth(e.target.checked)} />
          Show the broken service's metrics
        </label>
      </section>
      <ErrorNotice message={error ?? cases.error} />
      {cases.loading && <Loading what="Loading failures" />}
      {!state && !cases.loading && (
        <p className="muted">
          The detector is never told when the fault happens. It learns from the first rows and raises the
          alarm on its own. Recorded failures (listed first) behave like real systems; generated ones have
          drifting load and memory, so the detector can raise its alarm before the fault on them.
        </p>
      )}
      {state && <Live state={state} />}
    </div>
  );
}

function Live({ state }: { state: ReplayState }) {
  const current = state.state === "FINISHED" || state.state === "STOPPED" ? null : state.state;
  const reached = STEPS.indexOf(current ?? "EXPLAINED");
  return (
    <>
      <section className="panel stack">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="state-steps" aria-label="Replay state">
            {STEPS.map((step, i) => (
              <span
                key={step}
                className={`step${i < reached ? " done" : ""}${step === current ? " current" : ""}${step === current && step === "ALARM" ? " alarm" : ""}`}
              >
                {STEP_LABELS[step]}
              </span>
            ))}
            {(state.state === "FINISHED" || state.state === "STOPPED") && (
              <span className="step current">{state.state === "STOPPED" ? "Stopped" : "Finished"}</span>
            )}
          </div>
          <span className="small muted kbd">
            row {state.cursor} of {state.totalRows}
            {state.alarmTimeSec !== null && `, alarm at ${clock(state.alarmTimeSec)}`}
          </span>
        </div>
        <ProgressBar value={state.cursor} total={state.totalRows} />
        {state.error && <ErrorNotice message={`The analysis after the alarm failed: ${state.error}`} />}
        {state.state === "FINISHED" && state.alarmTimeSec === null && (
          <p className="muted">The case ended without an alarm: the detector saw nothing above its threshold.</p>
        )}
        <h3>Detector score</h3>
        <DetectorChart state={state} />
      </section>
      <section className="panel">
        <h3>The six metrics worth watching</h3>
        <div className="small-multiples">
          {state.series.map((s) => (
            <div key={s.column}>
              <div className="small muted">{s.column}</div>
              <SeriesChart
                timeSec={state.timeSec}
                series={[s]}
                height={110}
                markers={state.alarmTimeSec !== null ? [{ time: state.alarmTimeSec, label: "", color: cssVar("--cause") }] : []}
              />
            </div>
          ))}
        </div>
      </section>
      {state.run && (
        <div className="grid-2 slide-in">
          <ExplanationCard run={state.run} />
          <section className="panel">
            <h3>Cause or symptom</h3>
            <CauseSymptomChart services={state.run.response.services} />
            <Link to={`/cases/${encodeURIComponent(state.caseId)}`}>Open the full analysis of this failure</Link>
          </section>
        </div>
      )}
    </>
  );
}

/** The detector's row score with its threshold, and the alarm when it fires. */
function DetectorChart({ state }: { state: ReplayState }) {
  // A log axis, because a fault can push the score far above the threshold; a score
  // below 0.1 is drawn at 0.1, since a log scale has no zero.
  const data = state.timeSec.map((t, i) => {
    const s = state.detectorScore[i];
    return { t, score: s === null ? null : Math.max(0.1, s) };
  });
  const ink2 = cssVar("--ink-2");
  return (
    <div style={{ width: "100%", height: 200 }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke={cssVar("--grid")} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={clock} tick={{ fontSize: 11, fill: ink2 }} />
          <YAxis tick={{ fontSize: 11, fill: ink2 }} width={40} scale="log" domain={[0.1, "auto"]} allowDataOverflow />
          <Tooltip labelFormatter={(t) => clock(Number(t))} formatter={(v) => [one(Number(v)), "score"]} />
          <Line dataKey="score" stroke={cssVar("--accent")} dot={false} strokeWidth={2} isAnimationActive={false} />
          {state.threshold !== null && (
            <ReferenceLine y={state.threshold} stroke={cssVar("--ink-2")} strokeDasharray="4 3" label={{ value: `threshold ${one(state.threshold)}`, fontSize: 11, fill: ink2, position: "insideTopRight" }} />
          )}
          {state.alarmTimeSec !== null && (
            <ReferenceLine x={state.alarmTimeSec} stroke={cssVar("--cause")} label={{ value: "alarm", fontSize: 11, fill: cssVar("--cause"), position: "insideTopLeft" }} />
          )}
        </LineChart>
      </ResponsiveContainer>
      {state.threshold === null && <p className="small muted">Still learning what normal looks like; no scores yet.</p>}
    </div>
  );
}
