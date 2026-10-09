import type { ReactNode } from "react";

/** PARE in five steps, with one small picture each (docs/04 section 3.8). */
export function MethodPage() {
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>How it works</h1>
          <p>Propagation-aware residual explanations, step by step, and the live detector used in replay.</p>
        </div>
      </div>
      <ol className="steps-list panel" style={{ padding: "4px 20px" }}>
        <Step title="Learn what normal looks like" picture={<NormalBand />}>
          From the period before the problem, each metric gets a typical value (its median) and a typical spread
          (its median absolute deviation). How unusual a metric is later is measured in units of that spread, so
          one odd reading in the past cannot distort it.
        </Step>
        <Step title="Find when the change really began" picture={<ChangePoint />}>
          Detectors are late. Starting from the alarm, PARE looks back over the most unusual metrics for the moment
          their behaviour changed, and analyses from there rather than from the alarm. A late alarm then costs much
          less.
        </Step>
        <Step title="Subtract what the services it calls explain" picture={<Residual />}>
          For every service, a small model learns from normal data how its metrics follow the metrics of the
          services it calls. During the problem, PARE predicts each metric from those services and keeps only
          what is left over. A service that is slow only because it waits for another has almost nothing left
          over: it is a symptom.
        </Step>
        <Step title="Rank the services" picture={<Ranking />}>
          Each service is scored by its worst left-over metric. Starting from the service that looks worst, PARE
          walks down the call graph while a called service explains more of the trouble, and puts the service where
          the walk stops first. If even the top score is small, it says there is no clear cause rather than
          accusing anyone.
        </Step>
        <Step title="Explain it in words" picture={<Sentence />}>
          The answer is written from fixed templates: the likely cause and the metric that moved, which services
          were only affected and by how much, and when the change began. Every number in a sentence comes from the
          analysis.
        </Step>
      </ol>
      <section className="panel">
        <h2>The live detector in replay</h2>
        <p>
          Replay feeds a recorded failure to a detector written in Java, one row at a time. It is never told when
          the fault happens. It learns from the first rows, then scores each new row by its most unusual metric.
        </p>
        <p>
          The alarm threshold comes from conformal calibration: the learning rows are split in two, the first half
          sets what normal looks like, and the scores of the second half fix the threshold so that at most about 1%
          of normal rows would cross it. Three rows in a row above the threshold raise the alarm; a little later the
          analysis runs on the rows seen so far, and never on rows still to come.
        </p>
      </section>
      <section className="panel">
        <h2>What it cannot do</h2>
        <p>
          It works from metrics and a call graph. When callers overreact strongly to a slow service, or the graph is
          missing or wrong, no method working from metrics alone can separate cause from symptom reliably. Network
          faults such as packet loss are hard for every metric-only method.
        </p>
      </section>
    </div>
  );
}

function Step({ title, picture, children }: { title: string; picture: ReactNode; children: ReactNode }) {
  return (
    <li>
      <h3>{title}</h3>
      <div className="grid-2" style={{ alignItems: "center" }}>
        <p>{children}</p>
        <div>{picture}</div>
      </div>
    </li>
  );
}

const W = 320;
const H = 110;
const line = { stroke: "var(--accent)", strokeWidth: 2, fill: "none" };
const faint = { stroke: "var(--ink-3)", strokeWidth: 1, fill: "none", strokeDasharray: "4 3" };
const label = { fill: "var(--ink-2)", fontSize: 11 };

function Frame({ children, name }: { children: ReactNode; name: string }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={name}>
      {children}
    </svg>
  );
}

function NormalBand() {
  return (
    <Frame name="A metric staying inside its normal band">
      <rect x={10} y={40} width={300} height={30} style={{ fill: "var(--accent-soft)" }} />
      <polyline points="10,58 40,52 70,60 100,50 130,57 160,53 190,61 220,55 250,49 280,58 310,54" style={line} />
      <text x={14} y={34} style={label}>normal band: median ± spread</text>
    </Frame>
  );
}

function ChangePoint() {
  return (
    <Frame name="The change began before the alarm">
      <polyline points="10,75 90,73 120,76 130,40 200,38 310,41" style={line} />
      <line x1={130} y1={15} x2={130} y2={100} style={{ ...faint, stroke: "var(--ink-2)" }} />
      <line x1={230} y1={15} x2={230} y2={100} style={{ ...faint, stroke: "var(--cause)" }} />
      <text x={134} y={98} style={label}>change began</text>
      <text x={234} y={98} style={{ ...label, fill: "var(--cause)" }}>alarm</text>
    </Frame>
  );
}

function Residual() {
  return (
    <Frame name="Actual minus predicted leaves only the service's own part">
      <polyline points="10,80 120,80 130,35 310,35" style={line} />
      <polyline points="10,82 120,82 130,40 310,40" style={faint} />
      <text x={150} y={28} style={label}>actual and predicted rise together</text>
      <text x={150} y={62} style={label}>left over: small, so a symptom</text>
    </Frame>
  );
}

function Ranking() {
  const bar = (y: number, w: number, fill: string, name: string) => (
    <g>
      <rect x={110} y={y} width={w} height={18} rx={3} style={{ fill }} />
      <text x={100} y={y + 13} textAnchor="end" style={label}>
        {name}
      </text>
    </g>
  );
  return (
    <Frame name="Ranked by the left-over score">
      {bar(14, 190, "var(--cause)", "cartservice")}
      {bar(42, 60, "var(--symptom)", "checkout")}
      {bar(70, 40, "var(--symptom)", "frontend")}
    </Frame>
  );
}

function Sentence() {
  return (
    <Frame name="The explanation as a sentence">
      <rect x={10} y={20} width={300} height={70} rx={6} style={{ fill: "var(--surface-sunk)" }} />
      <text x={22} y={45} style={{ fill: "var(--ink)", fontSize: 12, fontWeight: 600 }}>Likely root cause: cartservice</text>
      <text x={22} y={65} style={label}>memory use moved 6.1 times its normal spread;</text>
      <text x={22} y={80} style={label}>checkout is probably affected, not the cause.</text>
    </Frame>
  );
}
