import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorNotice, Loading } from "../components/Status";
import { useAsync } from "../lib/useAsync";

const SOURCES = ["", "RCAEVAL_RE1", "RCAEVAL_RE2", "SYNTHETIC", "UPLOAD"];
const FAULTS = ["", "CPU", "MEM", "DISK", "DELAY", "LOSS", "LATENCY", "ERROR"];
const PAGE = 50;

/** Every recorded and generated failure, with filters (docs/04 section 3.2). */
export function CasesPage() {
  const [source, setSource] = useState("");
  const [system, setSystem] = useState("");
  const [faultType, setFaultType] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const navigate = useNavigate();
  const cases = useAsync(
    () => api.cases({ source, system, faultType, search, page, size: PAGE }),
    [source, system, faultType, search, page],
  );

  const reset = (apply: () => void) => {
    apply();
    setPage(0);
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Failures</h1>
          <p>Recorded failures from the RCAEval benchmark, generated ones from the lab, and your uploads.</p>
        </div>
      </div>
      <div className="row panel">
        <label className="field">
          Source
          <select value={source} onChange={(e) => reset(() => setSource(e.target.value))}>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {s || "any"}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          System
          <select value={system} onChange={(e) => reset(() => setSystem(e.target.value))}>
            <option value="">any</option>
            <option value="online-boutique">online-boutique</option>
            <option value="sock-shop">sock-shop</option>
            <option value="train-ticket">train-ticket</option>
            <option value="synthetic-8">synthetic-8</option>
          </select>
        </label>
        <label className="field">
          Fault type
          <select value={faultType} onChange={(e) => reset(() => setFaultType(e.target.value))}>
            {FAULTS.map((f) => (
              <option key={f} value={f}>
                {f || "any"}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ flex: 1, minWidth: 200 }}>
          Search case id
          <input value={search} placeholder="e.g. cartservice_mem" onChange={(e) => reset(() => setSearch(e.target.value))} />
        </label>
      </div>
      <ErrorNotice message={cases.error} />
      {cases.loading && !cases.data && <Loading what="Loading failures" />}
      {cases.data && (
        <section className="panel">
          <p className="small muted">
            {cases.data.total} failures. Click one to analyse it.
          </p>
          {cases.data.total === 0 ? (
            <p>
              No failure matches. Clear a filter, generate one in the synthetic lab, or export the benchmark
              cases with <code>experiments/export_cases.py</code>.
            </p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Source</th>
                  <th>System</th>
                  <th>Fault</th>
                  <th>Broken service</th>
                  <th className="num">Rows</th>
                  <th className="num">Metrics</th>
                </tr>
              </thead>
              <tbody>
                {cases.data.items.map((c) => (
                  <tr key={c.caseId} className="clickable" onClick={() => navigate(`/cases/${encodeURIComponent(c.caseId)}`)}>
                    <td>
                      <a href={`/cases/${encodeURIComponent(c.caseId)}`} onClick={(e) => e.preventDefault()}>
                        {c.caseId}
                      </a>
                    </td>
                    <td>{c.source}</td>
                    <td>{c.system}</td>
                    <td>{c.faultType}</td>
                    <td>{c.gtService ?? "unknown"}</td>
                    <td className="num">{c.nRows}</td>
                    <td className="num">{c.nColumns}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {cases.data.total > PAGE && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </button>
              <span className="small muted">
                Page {page + 1} of {Math.ceil(cases.data.total / PAGE)}
              </span>
              <button className="secondary" disabled={(page + 1) * PAGE >= cases.data.total} onClick={() => setPage(page + 1)}>
                Next
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
