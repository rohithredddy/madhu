// The only place the frontend talks to the network. Every call goes to the Java
// backend under /api; the browser never calls the Python engine (docs/02).
import type {
  AnalysisRun,
  BenchmarkJob,
  BenchmarkRequest,
  CaseDetail,
  CasePage,
  CaseSummary,
  ColumnInfo,
  EngineInfo,
  Health,
  ReplayState,
  SeriesResponse,
  SyntheticSettings,
  UploadMeta,
} from "./types";

/** An error the backend described: its {error, details} body (docs/06 section 4). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly details: string | null,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, init);
  } catch {
    throw new ApiError("The backend is not reachable. Is it running on port 8080?", 0, null);
  }
  if (!response.ok) {
    let error = `Request failed (${response.status})`;
    let details: string | null = null;
    try {
      const body = await response.json();
      error = body.error ?? error;
      details = body.details ?? null;
    } catch {
      // not a JSON body: keep the status message
    }
    throw new ApiError(error, response.status, details);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  engines: () => request<EngineInfo[]>("/engines"),

  cases: (filter: { source?: string; system?: string; faultType?: string; search?: string; page?: number; size?: number }) =>
    request<CasePage>(`/cases${query(filter)}`),
  caseDetail: (caseId: string) => request<CaseDetail>(`/cases/${encodeURIComponent(caseId)}`),
  series: (caseId: string, columns: string[], maxPoints = 600, from?: number, to?: number) =>
    request<SeriesResponse>(
      `/cases/${encodeURIComponent(caseId)}/series${query({ columns: columns.join(","), maxPoints, from, to })}`,
    ),
  analyze: (caseId: string, engine: string, delaySeconds: number) =>
    post<AnalysisRun>(`/cases/${encodeURIComponent(caseId)}/analyze`, { engine, delaySeconds }),
  compare: (caseId: string, engines: string[], delaySeconds: number) =>
    post<AnalysisRun[]>(`/cases/${encodeURIComponent(caseId)}/compare`, { engines, delaySeconds }),

  runs: (caseId?: string) => request<AnalysisRun[]>(`/runs${query({ caseId })}`),
  run: (runId: string) => request<AnalysisRun>(`/runs/${runId}`),
  reportUrl: (runId: string) => `/api/runs/${runId}/report?format=md`,

  startReplay: (caseId: string, speed: number, engine: string) =>
    post<{ sessionId: string }>("/replay", { caseId, speed, engine }),
  replay: (sessionId: string, showGroundTruth: boolean) =>
    request<ReplayState>(`/replay/${sessionId}${query({ showGroundTruth: String(showGroundTruth) })}`),
  stopReplay: (sessionId: string) => request<void>(`/replay/${sessionId}`, { method: "DELETE" }),

  synthetic: (settings: SyntheticSettings) => post<CaseSummary>("/synthetic", settings),

  guessColumns: (header: string) => post<ColumnInfo[]>("/uploads/guess-columns", { header }),
  upload: (file: File, meta: UploadMeta) => {
    const form = new FormData();
    form.append("file", file);
    form.append("meta", new Blob([JSON.stringify(meta)], { type: "application/json" }));
    return request<CaseSummary>("/uploads", { method: "POST", body: form });
  },

  startBenchmark: (body: BenchmarkRequest) => post<BenchmarkJob>("/benchmarks", body),
  benchmark: (jobId: string) => request<BenchmarkJob>(`/benchmarks/${jobId}`),
  benchmarks: () => request<BenchmarkJob[]>("/benchmarks"),
  benchmarkCsvUrl: (jobId: string) => `/api/benchmarks/${jobId}/report?format=csv`,
};
