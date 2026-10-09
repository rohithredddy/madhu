// Small display helpers. Nothing here computes a result; it only prints one.

/** One decimal, or a dash for a missing number (never 0). */
export function one(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "–" : value.toFixed(1);
}

export function three(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "–" : value.toFixed(3);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "–" : `${Math.round(value * 100)}%`;
}

/** Epoch seconds as HH:MM:SS in UTC, the same clock the explanation sentences use. */
export function clock(epochSeconds: number | null | undefined): string {
  if (epochSeconds === null || epochSeconds === undefined) {
    return "–";
  }
  return new Date(epochSeconds * 1000).toISOString().slice(11, 19);
}

/** Readable engine names; the code name stays visible beside them where it matters. */
export const ENGINE_LABELS: Record<string, string> = {
  PARE: "PARE (proposed)",
  PARE_NO_RESIDUAL: "PARE without residuals",
  PARE_NO_CP: "PARE without change point",
  PARE_LGBM: "PARE with LightGBM",
  NSIGMA: "NSigma",
  SHAP_IFOREST: "Isolation Forest + SHAP",
  ECDF: "ECDF tail score",
  PCA_RECON: "PCA reconstruction",
  NSIGMA_JAVA_FALLBACK: "NSigma (Java fallback)",
};

export function engineLabel(engine: string): string {
  return ENGINE_LABELS[engine] ?? engine;
}

export function roleLabel(role: string): string {
  switch (role) {
    case "CAUSE":
      return "cause";
    case "SYMPTOM":
      return "symptom";
    case "ALSO_ABNORMAL":
      return "also abnormal";
    default:
      return "normal";
  }
}
