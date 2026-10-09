package com.xairca.backend.runs;

import com.xairca.backend.analyze.AnalyzeResponse;
import com.xairca.backend.cases.GroundTruth;
import com.xairca.backend.explain.Explanation;
import java.time.Instant;

/**
 * An analysis as React receives it (docs/06 section 4, {@code AnalysisRun}).
 *
 * @param groundTruth the known answer, or null for a case without one. Shown to the
 *     user beside the result; it was never part of the engine request.
 * @param evaluation how the answer compares with the ground truth, or null
 */
public record AnalysisRunDto(
        String runId,
        String caseId,
        String engine,
        String mode,
        int delaySeconds,
        Instant createdAt,
        long tookMs,
        AnalyzeResponse response,
        Explanation explanation,
        GroundTruth groundTruth,
        Evaluation evaluation) {

    /**
     * Correctness against ground truth. Ranks are 1-based positions in the returned
     * lists, null when the truth was not listed.
     */
    public record Evaluation(
            Integer rankGtService,
            Integer rankGtIndicator,
            boolean correctTop1,
            boolean correctTop3,
            Boolean symptomError) {}
}
