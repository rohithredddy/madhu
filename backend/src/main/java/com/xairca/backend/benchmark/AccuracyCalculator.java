package com.xairca.backend.benchmark;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * AC@k, Avg@5, ExpAC@k and the symptom rate over a set of results - the same
 * definitions as {@code pare/eval_metrics.py} (docs/03 section 4.9):
 *
 * <ul>
 *   <li>AC@k: share of cases whose true service is in the top k; a case whose truth
 *       was never ranked is a miss.</li>
 *   <li>Avg@5: mean of AC@1..AC@5.</li>
 *   <li>ExpAC@k: AC@k of the true indicator, over the cases that have one correct
 *       metric (the strict definition, docs/08 section 4).</li>
 *   <li>Symptom rate: symptom errors / wrong top-1 answers that could be judged
 *       (needs a call graph); null rather than 0 over nothing.</li>
 * </ul>
 * Engine answers here carry no ties at rank 1 that Java can see, so a rank is a plain
 * position, as in the Python scores for every engine except ECDF.
 */
@Component
public class AccuracyCalculator {

    /** One analysed case: what the summary needs from an AnalysisRun. */
    public record Result(String engine, int delaySeconds, Integer rankGtService, Integer rankGtIndicator,
                         boolean hasIndicatorTruth, Boolean symptomError, String verdict, long tookMs) {}

    public List<BenchmarkSummary.Row> summarise(List<Result> results) {
        Map<String, List<Result>> groups = new LinkedHashMap<>();
        for (Result r : results) {
            groups.computeIfAbsent(r.engine() + "|" + r.delaySeconds(), k -> new ArrayList<>()).add(r);
        }
        List<BenchmarkSummary.Row> rows = new ArrayList<>();
        for (List<Result> group : groups.values()) {
            Result first = group.get(0);
            List<Integer> service = group.stream().map(Result::rankGtService).toList();
            List<Integer> indicator = group.stream().filter(Result::hasIndicatorTruth)
                    .map(Result::rankGtIndicator).toList();
            rows.add(new BenchmarkSummary.Row(first.engine(), first.delaySeconds(), group.size(),
                    acAtK(service, 1), acAtK(service, 3), avgAt5(service),
                    indicator.isEmpty() ? null : acAtK(indicator, 1),
                    indicator.isEmpty() ? null : acAtK(indicator, 3), indicator.size(),
                    symptomRate(group),
                    (int) group.stream().filter(r -> "NO_CLEAR_CAUSE".equals(r.verdict())).count(),
                    group.stream().mapToLong(Result::tookMs).average().orElse(0)));
        }
        rows.sort(Comparator.comparing(BenchmarkSummary.Row::engine)
                .thenComparingInt(BenchmarkSummary.Row::delaySeconds));
        return rows;
    }

    public static double acAtK(List<Integer> ranks, int k) {
        if (ranks.isEmpty()) {
            return 0.0;
        }
        long hits = ranks.stream().filter(r -> r != null && r <= k).count();
        return (double) hits / ranks.size();
    }

    public static double avgAt5(List<Integer> ranks) {
        double sum = 0;
        for (int k = 1; k <= 5; k++) {
            sum += acAtK(ranks, k);
        }
        return sum / 5.0;
    }

    public static Double symptomRate(List<Result> results) {
        int judged = 0;
        int symptoms = 0;
        for (Result r : results) {
            boolean wrong = r.rankGtService() == null || r.rankGtService() != 1;
            if (wrong && r.symptomError() != null) {
                judged++;
                if (r.symptomError()) {
                    symptoms++;
                }
            }
        }
        return judged == 0 ? null : (double) symptoms / judged;
    }
}
