import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ServiceRanking } from "../api/types";
import { cssVar, roleColor } from "../lib/colors";
import { one, percent, roleLabel } from "../lib/format";

export interface CauseSymptomRow {
  service: string;
  marginal: number;
  self: number;
  role: ServiceRanking["role"];
  inherited: number | null;
}

/**
 * The data behind the chart: one row per service, sorted by its own (self) score,
 * at most {@code limit} rows. Exported for a test, because a wrong mapping here would
 * show a gap between "looks unusual" and "its own problem" that is not in the data.
 */
export function causeSymptomRows(services: ServiceRanking[], limit = 8): CauseSymptomRow[] {
  return [...services]
    .map((s) => ({
      service: s.service,
      marginal: s.marginalScore ?? 0,
      self: s.score ?? 0,
      role: s.role,
      inherited: s.inheritedFraction,
    }))
    .sort((a, b) => b.self - a.self || a.service.localeCompare(b.service))
    .slice(0, limit);
}

/**
 * The key chart (docs/04 section 3.3): for each service, how unusual it looks (grey)
 * next to how much of that is its own problem (coloured by role). A symptom has a
 * tall grey bar and a short coloured one.
 */
export function CauseSymptomChart({ services, limit = 8 }: { services: ServiceRanking[]; limit?: number }) {
  const rows = causeSymptomRows(services, limit);
  if (!rows.length) {
    return <p className="muted">No services were scored.</p>;
  }
  const grid = cssVar("--grid");
  const ink2 = cssVar("--ink-2");
  return (
    <div style={{ width: "100%", height: 260 }}>
      <ResponsiveContainer>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 8 }} barGap={2}>
          <CartesianGrid vertical={false} stroke={grid} />
          <XAxis dataKey="service" tick={{ fontSize: 11, fill: ink2 }} interval={0} angle={-20} textAnchor="end" height={50} />
          <YAxis tick={{ fontSize: 11, fill: ink2 }} width={36} />
          <Tooltip
            formatter={(value, name) => [one(Number(value)), name]}
            labelFormatter={(label, payload) => {
              const row = payload?.[0]?.payload as CauseSymptomRow | undefined;
              return row ? `${label}: ${roleLabel(row.role)}, inherited ${percent(row.inherited)}` : String(label);
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar dataKey="marginal" name="How unusual it looks" fill={cssVar("--normal")} radius={[3, 3, 0, 0]} />
          <Bar dataKey="self" name="Its own problem" radius={[3, 3, 0, 0]} fill={cssVar("--cause")}>
            {rows.map((row) => (
              <Cell key={row.service} fill={roleColor(row.role)} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
