package com.xairca.backend.analyze;

import java.util.List;

/**
 * The engine's answer, exactly as docs/06 section 3 defines it. Numbers are boxed
 * because the contract allows {@code null} for "not available".
 *
 * @param verdict ROOT_CAUSE_FOUND or NO_CLEAR_CAUSE
 */
public record AnalyzeResponse(
        String requestId,
        String engine,
        String engineVersion,
        Long tookMs,
        String verdict,
        Double alarmTimeSec,
        Double changePointSec,
        Double windowStartSec,
        Double windowEndSec,
        List<ServiceRanking> services,
        List<IndicatorRanking> indicators,
        List<String> warnings) {

    public static final String ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND";
    public static final String NO_CLEAR_CAUSE = "NO_CLEAR_CAUSE";

    public AnalyzeResponse {
        services = services == null ? List.of() : List.copyOf(services);
        indicators = indicators == null ? List.of() : List.copyOf(indicators);
        warnings = warnings == null ? List.of() : List.copyOf(warnings);
    }

    /** A copy with extra warnings appended (e.g. "engine not available, Java fallback used"). */
    public AnalyzeResponse withWarnings(List<String> extra) {
        List<String> all = new java.util.ArrayList<>(warnings);
        all.addAll(extra);
        return new AnalyzeResponse(requestId, engine, engineVersion, tookMs, verdict, alarmTimeSec,
                changePointSec, windowStartSec, windowEndSec, services, indicators, all);
    }

    /** One service in the ranking. role: CAUSE, SYMPTOM, ALSO_ABNORMAL or NORMAL. */
    public record ServiceRanking(
            String service,
            int rank,
            Double score,
            Double marginalScore,
            Double inheritedFraction,
            String topIndicator,
            String role,
            String explainedBy) {}

    /** One metric column in the indicator ranking. */
    public record IndicatorRanking(
            String column,
            String service,
            String metric,
            int rank,
            Double selfScore,
            Double marginalScore,
            Double inheritedFraction) {}
}
