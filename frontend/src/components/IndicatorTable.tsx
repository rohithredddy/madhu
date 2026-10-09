import type { IndicatorRanking } from "../api/types";
import { one, percent } from "../lib/format";

/** The returned indicators (up to topK) with their scores (docs/04 section 3.3). */
export function IndicatorTable({ indicators, truth }: { indicators: IndicatorRanking[]; truth?: string | null }) {
  return (
    <table>
      <thead>
        <tr>
          <th className="num">Rank</th>
          <th>Metric</th>
          <th>Service</th>
          <th className="num">Own score</th>
          <th className="num">Looks</th>
          <th className="num">Inherited</th>
        </tr>
      </thead>
      <tbody>
        {indicators.map((i) => (
          <tr key={i.column}>
            <td className="num">{i.rank}</td>
            <td>
              {i.column}
              {truth === i.column && <span className="badge truth" style={{ marginLeft: 6 }}>known answer</span>}
            </td>
            <td>{i.service}</td>
            <td className="num">{one(i.selfScore)}</td>
            <td className="num">{one(i.marginalScore)}</td>
            <td className="num">{percent(i.inheritedFraction)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
