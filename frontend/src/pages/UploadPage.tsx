import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ColumnInfo, Edge } from "../api/types";
import { CallGraphView } from "../components/CallGraphView";
import { ErrorNotice } from "../components/Status";
import { describe } from "../lib/useAsync";

/**
 * Bring your own data (docs/04 section 3.7): a CSV with a "time" column, the meaning
 * of each column, the call graph, and when the problem started.
 */
export function UploadPage() {
  const navigate = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [columns, setColumns] = useState<ColumnInfo[]>([]);
  const [graphText, setGraphText] = useState("");
  const [caseId, setCaseId] = useState("");
  const [system, setSystem] = useState("");
  const [faultType, setFaultType] = useState("");
  const [injectTime, setInjectTime] = useState("");
  const [gtService, setGtService] = useState("");
  const [gtIndicator, setGtIndicator] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const choose = async (picked: File | null) => {
    setFile(picked);
    setColumns([]);
    setError(null);
    if (!picked) {
      return;
    }
    const header = (await picked.slice(0, 64 * 1024).text()).split(/\r?\n/)[0];
    if (!header.split(",").map((h) => h.trim()).includes("time")) {
      setError('The first line must be a header that includes a "time" column (epoch seconds).');
      return;
    }
    try {
      setColumns(await api.guessColumns(header));
      setCaseId(picked.name.replace(/\.csv$/i, "").replace(/[^A-Za-z0-9._-]/g, "-"));
    } catch (e) {
      setError(describe(e));
    }
  };

  const edges = useMemo<Edge[]>(
    () =>
      graphText
        .split(/\r?\n/)
        .map((line) => line.split("->").map((part) => part.trim()))
        .filter((parts) => parts.length === 2 && parts[0] && parts[1])
        .map(([from, to]) => ({ from, to })),
    [graphText],
  );
  const services = Array.from(new Set(columns.map((c) => c.service)));

  const edit = (index: number, key: "service" | "metric", value: string) =>
    setColumns((list) => list.map((c, i) => (i === index ? { ...c, [key]: value } : c)));

  const submit = async () => {
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const summary = await api.upload(file, {
        caseId,
        system,
        faultType,
        injectTimeSec: injectTime ? Number(injectTime) : null,
        columns,
        graphText,
        gtService,
        gtIndicator,
      });
      navigate(`/cases/${encodeURIComponent(summary.caseId)}`);
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Upload data</h1>
          <p>Analyse your own system: a CSV of metrics over time, plus who calls whom.</p>
        </div>
      </div>
      <ol className="steps-list">
        <li>
          <h3>Choose the CSV</h3>
          <p className="small muted">One row per moment. The first column is "time" in epoch seconds; then one column per metric, such as cartservice_mem.</p>
          <input type="file" accept=".csv,text/csv" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        </li>
        <li>
          <h3>Check what each column measures</h3>
          {columns.length === 0 ? (
            <p className="small muted">The guess appears here once a file is chosen. It splits each name at the last underscore.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Column</th>
                  <th>Service</th>
                  <th>Metric</th>
                </tr>
              </thead>
              <tbody>
                {columns.map((c, i) => (
                  <tr key={c.name}>
                    <td>{c.name}</td>
                    <td>
                      <input value={c.service} onChange={(e) => edit(i, "service", e.target.value)} aria-label={`service of ${c.name}`} />
                    </td>
                    <td>
                      <input value={c.metric} onChange={(e) => edit(i, "metric", e.target.value)} aria-label={`metric of ${c.name}`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </li>
        <li>
          <h3>Describe the call graph</h3>
          <p className="small muted">One line per call, caller first: frontend -&gt; cartservice. Leave it empty if you do not know it; the analysis then cannot tell causes from symptoms.</p>
          <div className="grid-2">
            <textarea rows={8} value={graphText} onChange={(e) => setGraphText(e.target.value)} placeholder={"frontend -> checkout\ncheckout -> cartservice"} />
            {services.length > 0 && <CallGraphView graph={{ source: "USER", edges }} services={services} />}
          </div>
        </li>
        <li>
          <h3>When did the problem start, and do you know the cause?</h3>
          <div className="row">
            <label className="field">
              Problem started (epoch seconds)
              <input value={injectTime} onChange={(e) => setInjectTime(e.target.value.replace(/[^0-9]/g, ""))} />
            </label>
            <label className="field">
              Case name
              <input value={caseId} onChange={(e) => setCaseId(e.target.value)} />
            </label>
            <label className="field">
              System name
              <input value={system} onChange={(e) => setSystem(e.target.value)} placeholder="optional" />
            </label>
            <label className="field">
              Fault type
              <input value={faultType} onChange={(e) => setFaultType(e.target.value)} placeholder="optional, e.g. MEM" />
            </label>
            <label className="field">
              Broken service, if known
              <select value={gtService} onChange={(e) => setGtService(e.target.value)}>
                <option value="">not known</option>
                {services.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Broken metric, if known
              <select value={gtIndicator} onChange={(e) => setGtIndicator(e.target.value)}>
                <option value="">not known</option>
                {columns.filter((c) => c.service === gtService).map((c) => (
                  <option key={c.name} value={c.name}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="small muted">At least 60 rows must come before this time, so there is normal behaviour to learn from.</p>
        </li>
      </ol>
      <ErrorNotice message={error} />
      <div>
        <button disabled={!file || !columns.length || !injectTime || busy} onClick={submit}>
          {busy ? "Uploading…" : "Upload and open"}
        </button>
      </div>
    </div>
  );
}
