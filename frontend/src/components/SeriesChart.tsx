import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cssVar, seriesColor } from "../lib/colors";
import { clock } from "../lib/format";

export interface Marker {
  time: number;
  label: string;
  color: string;
}

/**
 * Metric lines over time with vertical markers for the injection, the alarm and the
 * estimated change point (docs/04 section 3.3). Each series is scaled to its own
 * normal range so metrics of very different units can share one chart; the tooltip
 * shows the real values.
 */
export function SeriesChart({
  timeSec,
  series,
  markers = [],
  height = 240,
  normalise = true,
}: {
  timeSec: number[];
  series: { column: string; values: (number | null)[] }[];
  markers?: Marker[];
  height?: number;
  normalise?: boolean;
}) {
  const scaled = series.map((s) => (normalise ? rescale(s.values) : s.values));
  const data = timeSec.map((t, i) => {
    const row: Record<string, number | null> = { t };
    series.forEach((s, k) => {
      row[s.column] = scaled[k][i];
      row[`${s.column}__raw`] = s.values[i];
    });
    return row;
  });
  const ink2 = cssVar("--ink-2");
  return (
    <div style={{ width: "100%", height }}>
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke={cssVar("--grid")} />
          <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} tickFormatter={clock} tick={{ fontSize: 11, fill: ink2 }} />
          <YAxis tick={{ fontSize: 11, fill: ink2 }} width={36} hide={normalise} />
          <Tooltip
            labelFormatter={(t) => clock(Number(t))}
            formatter={(_value, name, item) => {
              const raw = (item?.payload as Record<string, number | null>)[`${String(name)}__raw`];
              return [raw === null || raw === undefined ? "missing" : raw.toPrecision(4), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          {series.map((s, k) => (
            <Line key={s.column} dataKey={s.column} stroke={seriesColor(k)} dot={false} strokeWidth={2} isAnimationActive={false} connectNulls={false} />
          ))}
          {markers.map((m) => (
            <ReferenceLine key={m.label} x={m.time} stroke={m.color} strokeDasharray="4 3" label={{ value: m.label, fontSize: 11, fill: m.color, position: "insideTopLeft" }} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Scale to 0..1 over the series' own range, keeping missing values missing. */
export function rescale(values: (number | null)[]): (number | null)[] {
  const present = values.filter((v): v is number => v !== null && Number.isFinite(v));
  if (!present.length) {
    return values.map(() => null);
  }
  const lo = Math.min(...present);
  const hi = Math.max(...present);
  const span = hi - lo || 1;
  return values.map((v) => (v === null || !Number.isFinite(v) ? null : (v - lo) / span));
}
