// Chart libraries need real colour values, not CSS classes. These read the CSS
// variables from styles.css, so the palette is defined in exactly one place.

export function cssVar(name: string, fallback = "#999999"): string {
  if (typeof document === "undefined") {
    return fallback;
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function roleColor(role: string): string {
  switch (role) {
    case "CAUSE":
      return cssVar("--cause");
    case "SYMPTOM":
      return cssVar("--symptom");
    case "ALSO_ABNORMAL":
      return cssVar("--also-abnormal");
    default:
      return cssVar("--normal");
  }
}

/** Fixed categorical slots, in order; a series keeps its slot, never its rank. */
export function seriesColor(index: number): string {
  return cssVar(`--series-${(index % 4) + 1}`);
}
