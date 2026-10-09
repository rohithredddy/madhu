import type { EngineInfo } from "../api/types";
import { engineLabel } from "../lib/format";

/** Which engine to run. Lists what the backend reports as available. */
export function EngineSelect({
  engines,
  value,
  onChange,
  label = "Engine",
}: {
  engines: EngineInfo[];
  value: string;
  onChange: (engine: string) => void;
  label?: string;
}) {
  return (
    <label className="field">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {engines.map((e) => (
          <option key={e.name} value={e.name} title={e.description}>
            {engineLabel(e.name)}
          </option>
        ))}
      </select>
    </label>
  );
}

/** How late the detector is assumed to be: 0 to 120 s (docs/04 section 3.3). */
export function DelaySlider({ value, onChange }: { value: number; onChange: (seconds: number) => void }) {
  return (
    <label className="field">
      Detection delay: {value} s
      <input type="range" min={0} max={120} step={10} value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

export function ProgressBar({ value, total, label }: { value: number; total: number; label?: string }) {
  const pct = total > 0 ? Math.min(100, (100 * value) / total) : 0;
  return (
    <div>
      {label && <div className="small muted">{label}</div>}
      <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={total}>
        <div style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
