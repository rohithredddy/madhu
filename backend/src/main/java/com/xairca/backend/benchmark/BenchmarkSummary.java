package com.xairca.backend.benchmark;

import java.util.List;

/**
 * Accuracy per engine and delay, and every failure (docs/06 section 4).
 *
 * @param rows one row per (engine, delay)
 * @param failed every cell that did not produce a result, so none is dropped silently
 */
public record BenchmarkSummary(List<Row> rows, List<Failure> failed) {

    /**
     * @param expAc1 strict indicator accuracy, over the cases that have one correct
     *     metric (null when there are none); {@code expCases} says how many
     * @param symptomRate of the wrong top-1 answers that could be judged, the share
     *     that blamed a caller of the culprit; null when none could be
     */
    public record Row(String engine, int delaySeconds, int cases, double ac1, double ac3, double avg5,
                      Double expAc1, Double expAc3, int expCases, Double symptomRate, int noClearCause,
                      double meanMs) {}

    public record Failure(String caseId, String engine, int delaySeconds, String error) {}
}
