import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { BenchmarkJob, BenchmarkRow } from "../api/types";
import { ProgressBar } from "../components/Controls";
import { ErrorNotice } from "../components/Status";
import { cssVar, seriesColor } from "../lib/colors";
import { engineLabel, percent, three } from "../lib/format";
import { describe, useAsync } from "../lib/useAsync";

const DELAYS = [0, 30, 60, 120];

/** Run many analyses at once and see accuracy per engine and delay (docs/04 section 3.6). */
export function BenchmarkPage() {
  const engines = useAsync(() => api.engines(), []);
  const [source, setSource] = useState("");
  const [system, setSystem] = useState("");
  const [faultType, setFaultType] = useState("");
  const [maxCases, setMaxCases] = useState(20);
  const [chosen, setChosen] = useState<string[]>(["PARE", "NSIGMA"]);
  const [delays, setDelays] = useState<number[]>([0]);
  const [job, setJob] = useState<BenchmarkJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the job until it ends.
  useEffect(() => {
    if (!job || job.status === "DONE" || job.status === "FAILED") {
      return;
    }
    const timer = setTimeout(() => api.benchmark(job.id).then(setJob).catch((e) => setError(describe(e))), 1500);
    return () => clearTimeout(timer);
  }, [job]);

  const toggle = <T,>(list: T[], value: T) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);

  const start = async () => {
    setError(null);
    try {
      setJob(await api.startBenchmark({ source, system, faultType, maxCases, engines: chosen, delays }));
    } catch (e) {
      setError(describe(e));
    }
  };

  const rows = job?.summary?.rows ?? [];
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Benchmark</h1>
          <p>Analyse many failures with several engines and compare how often each finds the broken service.</p>
        </div>
      </div>
      <section className="panel stack">
        <div className="row">
          <label className="field">
            Source
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">any</option>
              <option value="RCAEVAL_RE1">RCAEVAL_RE1</option>
              <option value="SYNTHETIC">SYNTHETIC</option>
              <option value="UPLOAD">UPLOAD</option>
            </select>
          </label>
          <label className="field">
            System
            <select value={system} onChange={(e) => setSystem(e.target.value)}>
              <option value="">any</option>
              <option value="online-boutique">online-boutique</option>
              <option value="sock-shop">sock-shop</option>
              <option value="train-ticket">train-ticket</option>
            </select>
          </label>
          <label className="field">
            Fault type
            <select value={faultType} onChange={(e) => setFaultType(e.target.value)}>
              {["", "CPU", "MEM", "DISK", "DELAY", "LOSS", "LATENCY", "ERROR"].map((f) => (
                <option key={f} value={f}>
                  {f || "any"}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            At most this many cases
            <input type="number" min={1} max={400} value={maxCases} onChange={(e) => setMaxCases(Number(e.target.value))} style={{ width: 100 }} />
          </label>
        </div>
        <fieldset className="row" style={{ border: "none", padding: 0 }}>
          <legend className="small muted">Engines</legend>
          {(engines.data ?? []).filter((e) => e.available).map((e) => (
            <label key={e.name} className="row small" style={{ gap: 4 }}>
              <input type="checkbox" checked={chosen.includes(e.name)} onChange={() => setChosen(toggle(chosen, e.name))} />
              {engineLabel(e.name)}
            </label>
          ))}
        </fieldset>
        <fieldset className="row" style={{ border: "none", padding: 0 }}>
          <legend className="small muted">Detection delays</legend>
          {DELAYS.map((d) => (
            <label key={d} className="row small" style={{ gap: 4 }}>
              <input type="checkbox" checked={delays.includes(d)} onChange={() => setDelays(toggle(delays, d).sort((a, b) => a - b))} />
              {d} s
            </label>
          ))}
        </fieldset>
        <div className="row">
          <button disabled={!chosen.length || !delays.length || (!!job && job.status === "RUNNING")} onClick={start}>
            Start benchmark
          </button>
          <span className="small muted">
            The paper's numbers come from the research scripts; this page reproduces them interactively.
          </span>
        </div>
      </section>
      <ErrorNotice message={error ?? engines.error} />
      {job && (
        <section className="panel stack">
          <ProgressBar value={job.done} total={job.total} label={`${job.status.toLowerCase()}: ${job.done} of ${job.total} analyses, ${job.failed} failed`} />
          {job.summary && <Results rows={rows} />}
          {job.summary && job.summary.failed.length > 0 && (
            <details>
              <summary className="small">{job.summary.failed.length} analyses failed</summary>
              <ul className="small">
                {job.summary.failed.map((f, i) => (
                  <li key={i}>
                    {f.caseId}, {f.engine}, {f.delaySeconds} s: {f.error}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {job.status === "DONE" && (
            <a className="small" href={api.benchmarkCsvUrl(job.id)} download>
              Download every result (CSV)
            </a>
          )}
        </section>
      )}
    </div>
  );
}

function Results({ rows }: { rows: BenchmarkRow[] }) {
  const engines = Array.from(new Set(rows.map((r) => r.engine)));
  const delays = Array.from(new Set(rows.map((r) => r.delaySeconds))).sort((a, b) => a - b);
  const firstDelay = delays[0];
  const barData = rows.filter((r) => r.delaySeconds === firstDelay).map((r) => ({ engine: engineLabel(r.engine), ac1: r.ac1 }));
  const lineData = delays.map((d) => {
    const point: Record<string, number> = { delay: d };
    for (const r of rows.filter((x) => x.delaySeconds === d)) {
      point[r.engine] = r.avg5;
    }
    return point;
  });
  const ink2 = cssVar("--ink-2");
  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Engine</th>
            <th className="num">Delay s</th>
            <th className="num">Cases</th>
            <th className="num">AC@1</th>
            <th className="num">AC@3</th>
            <th className="num">Avg@5</th>
            <th className="num">ExpAC@3</th>
            <th className="num">Symptom rate</th>
            <th className="num">No clear cause</th>
            <th className="num">Mean ms</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.engine}-${r.delaySeconds}`}>
              <td>{engineLabel(r.engine)}</td>
              <td className="num">{r.delaySeconds}</td>
              <td className="num">{r.cases}</td>
              <td className="num">{three(r.ac1)}</td>
              <td className="num">{three(r.ac3)}</td>
              <td className="num">{three(r.avg5)}</td>
              <td className="num" title={`over ${r.expCases} cases with one correct metric`}>{three(r.expAc3)}</td>
              <td className="num">{percent(r.symptomRate)}</td>
              <td className="num">{r.noClearCause}</td>
              <td className="num">{Math.round(r.meanMs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">
        AC@k: the broken service is in the top k. ExpAC@3: the right metric is in the top 3, over the cases where
        one metric is clearly right. Symptom rate: of the wrong answers, the share that blamed a caller of the
        broken service.
      </p>
      <div className="grid-2">
        <div>
          <h3>AC@1 at {firstDelay} s delay</h3>
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={barData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                <CartesianGrid vertical={false} stroke={cssVar("--grid")} />
                <XAxis dataKey="engine" tick={{ fontSize: 11, fill: ink2 }} interval={0} />
                <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: ink2 }} width={36} />
                <Tooltip formatter={(v) => three(Number(v))} />
                <Bar dataKey="ac1" name="AC@1" fill={cssVar("--accent")} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
        {delays.length > 1 && (
          <div>
            <h3>Avg@5 as the alarm comes later</h3>
            <div style={{ width: "100%", height: 220 }}>
              <ResponsiveContainer>
                <LineChart data={lineData} margin={{ top: 8, right: 12, left: 0, bottom: 8 }}>
                  <CartesianGrid vertical={false} stroke={cssVar("--grid")} />
                  <XAxis dataKey="delay" tick={{ fontSize: 11, fill: ink2 }} unit=" s" />
                  <YAxis domain={[0, 1]} tick={{ fontSize: 11, fill: ink2 }} width={36} />
                  <Tooltip formatter={(v) => three(Number(v))} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {engines.map((e, i) => (
                    <Line key={e} dataKey={e} name={engineLabel(e)} stroke={seriesColor(i)} strokeWidth={2} />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
