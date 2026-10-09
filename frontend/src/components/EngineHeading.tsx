import { engineLabel } from "../lib/format";

/**
 * The engine a column was asked for. When the Python engine could not answer in time,
 * the Java fallback answered instead, and the heading says so rather than silently
 * showing a different engine's result under the requested name.
 */
export function EngineHeading({ asked, answered }: { asked: string; answered: string }) {
  return (
    <h2>
      {engineLabel(asked)}
      {answered !== asked && (
        <span className="small muted" style={{ display: "block", fontWeight: 400 }}>
          not available just now: {engineLabel(answered)} answered instead
        </span>
      )}
    </h2>
  );
}
