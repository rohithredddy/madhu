import { Link } from "react-router-dom";

/** The idea in one paragraph and one picture, and the ways in (docs/04 section 3.1). */
export function HomePage() {
  return (
    <div className="stack">
      <section className="hero">
        <div>
          <h1>The loudest service is often not the broken one.</h1>
          <p className="lede">
            When one microservice fails, every service that calls it slows down too. Ordinary anomaly
            explanations point at whatever moved most, and that is usually a victim. PARE learns how each
            service depends on the services it calls, subtracts what they explain, and names the service whose
            trouble is its own.
          </p>
          <p className="muted">
            Every failure here has a known answer, so you can check whether each explanation was right.
          </p>
          <div className="row" style={{ marginTop: 16 }}>
            <Link className="button" to="/cases">
              Try a real failure
            </Link>
            <Link className="button secondary" to="/replay">
              Watch a replay
            </Link>
            <Link className="button secondary" to="/lab">
              Open the synthetic lab
            </Link>
            <Link className="button secondary" to="/benchmark">
              See the benchmark
            </Link>
          </div>
        </div>
        <IdeaPicture />
      </section>
    </div>
  );
}

/**
 * The project's motivating example as a picture: cartservice's memory leaks (red),
 * checkout and frontend slow down only because they wait for it (orange), payment
 * is unaffected (grey).
 */
function IdeaPicture() {
  const node = (x: number, y: number, label: string, fill: string, ink: string, note: string) => (
    <g>
      <rect x={x - 70} y={y - 22} width={140} height={44} rx={8} style={{ fill }} />
      <text x={x} y={y - 2} textAnchor="middle" style={{ fill: ink, fontSize: 15, fontWeight: 600 }}>
        {label}
      </text>
      <text x={x} y={y + 14} textAnchor="middle" style={{ fill: ink, fontSize: 11 }}>
        {note}
      </text>
    </g>
  );
  const arrow = (x1: number, y1: number, x2: number, y2: number) => (
    <line x1={x1} y1={y1} x2={x2} y2={y2} style={{ stroke: "var(--ink-3)", strokeWidth: 2 }} markerEnd="url(#head)" />
  );
  return (
    <figure style={{ margin: 0 }} className="panel">
      <svg viewBox="0 0 420 300" role="img" aria-label="Cart service is the cause; checkout and frontend are only affected; payment is normal">
        <defs>
          <marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" style={{ fill: "var(--ink-3)" }} />
          </marker>
        </defs>
        {arrow(210, 62, 210, 116)}
        {arrow(195, 162, 130, 216)}
        {arrow(225, 162, 290, 216)}
        {node(210, 40, "frontend", "var(--symptom)", "var(--ink)", "slow, but only waiting")}
        {node(210, 140, "checkout", "var(--symptom)", "var(--ink)", "slow, but only waiting")}
        {node(110, 240, "cartservice", "var(--cause)", "var(--surface)", "memory leak: the cause")}
        {node(310, 240, "payment", "var(--surface-sunk)", "var(--ink-2)", "normal")}
      </svg>
      <figcaption className="small muted">
        Arrows point from a caller to the service it calls. A fault travels upward, against the arrows.
      </figcaption>
    </figure>
  );
}
