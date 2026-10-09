// Types of everything the backend sends, matching docs/06_DATA_CONTRACTS.md.
// A missing number is null, never 0.

export type Role = "CAUSE" | "SYMPTOM" | "ALSO_ABNORMAL" | "NORMAL";
export type Verdict = "ROOT_CAUSE_FOUND" | "NO_CLEAR_CAUSE";

export interface ColumnInfo {
  name: string;
  service: string;
  metric: string;
}

export interface Edge {
  from: string;
  to: string;
}

export interface CallGraph {
  source: string;
  edges: Edge[];
}

export interface GroundTruth {
  service: string;
  /** null when the fault type has no single right metric (DISK, DELAY, LOSS). */
  indicator: string | null;
}

export interface CaseMeta {
  caseId: string;
  source: string;
  system: string;
  faultType: string;
  injectTimeSec: number;
  groundTruth: GroundTruth | null;
  columns: ColumnInfo[];
  graph: CallGraph;
  notes: string | null;
}

export interface CaseSummary {
  caseId: string;
  source: string;
  system: string;
  faultType: string;
  gtService: string | null;
  nRows: number;
  nColumns: number;
  replayable: boolean;
}

export interface CasePage {
  items: CaseSummary[];
  total: number;
  page: number;
  size: number;
}

export interface CaseDetail {
  summary: CaseSummary;
  meta: CaseMeta;
  firstTimeSec: number;
  lastTimeSec: number;
}

export interface SeriesResponse {
  timeSec: number[];
  series: { column: string; values: (number | null)[] }[];
  step: number;
}

export interface ServiceRanking {
  service: string;
  rank: number;
  score: number | null;
  marginalScore: number | null;
  inheritedFraction: number | null;
  topIndicator: string;
  role: Role;
  explainedBy: string | null;
}

export interface IndicatorRanking {
  column: string;
  service: string;
  metric: string;
  rank: number;
  selfScore: number | null;
  marginalScore: number | null;
  inheritedFraction: number | null;
}

export interface AnalyzeResponse {
  requestId: string | null;
  engine: string;
  engineVersion: string;
  tookMs: number | null;
  verdict: Verdict;
  alarmTimeSec: number | null;
  changePointSec: number | null;
  windowStartSec: number | null;
  windowEndSec: number | null;
  services: ServiceRanking[];
  indicators: IndicatorRanking[];
  warnings: string[];
}

export interface Explanation {
  headline: string;
  confidence: "HIGH" | "MEDIUM" | "LOW";
  causeSentences: string[];
  symptomSentences: string[];
  evidenceSentences: string[];
  notes: string[];
}

export interface Evaluation {
  rankGtService: number | null;
  rankGtIndicator: number | null;
  correctTop1: boolean;
  correctTop3: boolean;
  symptomError: boolean | null;
}

export interface AnalysisRun {
  runId: string;
  caseId: string;
  engine: string;
  mode: "ONE_CLICK" | "REPLAY" | "BENCHMARK";
  delaySeconds: number;
  createdAt: string;
  tookMs: number;
  response: AnalyzeResponse;
  explanation: Explanation;
  groundTruth: GroundTruth | null;
  evaluation: Evaluation | null;
}

export type ReplayPhase = "LEARNING" | "WATCHING" | "ALARM" | "EXPLAINED" | "FINISHED" | "STOPPED";

export interface ReplayState {
  sessionId: string;
  caseId: string;
  engine: string;
  state: ReplayPhase;
  cursor: number;
  totalRows: number;
  speed: number;
  threshold: number | null;
  timeSec: number[];
  detectorScore: (number | null)[];
  series: { column: string; values: (number | null)[] }[];
  alarmTimeSec: number | null;
  topColumnsAtAlarm: string[];
  run: AnalysisRun | null;
  error: string | null;
}

export interface EngineInfo {
  name: string;
  description: string;
  available: boolean;
}

export interface Health {
  status: string;
  engine: boolean;
  cases: number;
}

export interface SyntheticSettings {
  nServices: number;
  faultType: "LATENCY" | "CPU" | "MEM" | "ERROR";
  rootService: string | null;
  propagation: number;
  amplification: number;
  noise: "LOW" | "MEDIUM" | "HIGH";
  seed: number;
}

export interface BenchmarkRow {
  engine: string;
  delaySeconds: number;
  cases: number;
  ac1: number;
  ac3: number;
  avg5: number;
  expAc1: number | null;
  expAc3: number | null;
  expCases: number;
  symptomRate: number | null;
  noClearCause: number;
  meanMs: number;
}

export interface BenchmarkJob {
  id: string;
  createdAt: string;
  status: "QUEUED" | "RUNNING" | "DONE" | "FAILED";
  total: number;
  done: number;
  failed: number;
  engines: string[];
  delays: number[];
  summary: {
    rows: BenchmarkRow[];
    failed: { caseId: string; engine: string; delaySeconds: number; error: string }[];
  } | null;
}

export interface BenchmarkRequest {
  source?: string;
  system?: string;
  faultType?: string;
  maxCases?: number;
  engines: string[];
  delays: number[];
}

export interface UploadMeta {
  caseId: string;
  system: string;
  faultType: string;
  injectTimeSec: number | null;
  columns: ColumnInfo[];
  graphText: string;
  gtService: string;
  gtIndicator: string;
}
