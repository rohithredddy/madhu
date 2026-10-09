package com.xairca.backend.analyze;

import com.xairca.backend.analyze.AnalyzeResponse.IndicatorRanking;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import com.xairca.backend.cases.ColumnInfo;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * The Java NSigma ranker, used when the Python engine is not reachable.
 *
 * <p>It must rank exactly like Python's {@code NSIGMA} engine, and a test checks it
 * on the shared sample in analyzer/samples (docs/03 section 4.4). So it copies every
 * step of the Python path, in order:
 * <ol>
 *   <li>Cleaning (pare/preprocess.py): drop a column missing for more than half of
 *       the normal period; fill gaps of up to 3 rows (forward, or backward when the gap
 *       starts the series); drop a column that never moves in the normal period.</li>
 *   <li>Window: abnormal = recent rows from the alarm to the end. The change point is
 *       never used here.</li>
 *   <li>Score per column (pare/scores.py nsigma_score):
 *       {@code |mean(abnormal) - mean(normal)| / (std(normal) + eps)}, with
 *       {@code eps = 1e-6 * (|mean(normal)| + 1)}, population standard deviation,
 *       missing values skipped, and a score that cannot be computed counted as 0.</li>
 *   <li>Service score = its worst column. Services by score, then name; indicators by
 *       score, then column name.</li>
 *   <li>Verdict ROOT_CAUSE_FOUND when the top score is at least 3.0. Rank 1 is CAUSE only
 *       then; otherwise ALSO_ABNORMAL at 3.0 or more, else NORMAL. No residuals, so
 *       never SYMPTOM.</li>
 * </ol>
 */
@Component
public class FallbackRanker {

    public static final String ENGINE_NAME = "NSIGMA_JAVA_FALLBACK";
    static final double MAX_NAN_FRACTION = 0.5;
    static final int FILL_LIMIT = 3;
    static final double EPS_FACTOR = 1e-6;
    static final double MIN_CAUSE_SCORE = 3.0;
    static final double ABNORMAL_SCORE = 3.0;
    static final int DEFAULT_TOP_K = 10;

    /** Rank the services of one request. */
    public AnalyzeResponse rank(AnalyzeRequest request) {
        long started = System.nanoTime();
        List<ColumnInfo> columns = request.columns();
        double[][] normal = request.normal().toPrimitive();
        double[][] recent = request.recent().toPrimitive();
        long[] recentTimes = request.recent().timeSec();
        List<String> warnings = new ArrayList<>();

        // The abnormal window: recent rows at or after the alarm.
        List<Integer> windowRows = new ArrayList<>();
        for (int row = 0; row < recentTimes.length; row++) {
            if (recentTimes[row] >= request.alarmTimeSec()) {
                windowRows.add(row);
            }
        }

        List<IndicatorRanking> scored = new ArrayList<>();
        Map<String, Double> serviceScore = new LinkedHashMap<>();
        Map<String, String> serviceTop = new LinkedHashMap<>();
        for (int c = 0; c < columns.size(); c++) {
            ColumnInfo column = columns.get(c);
            double[] before = column(normal, c);
            if (nanFraction(before) > MAX_NAN_FRACTION) {
                warnings.add("dropped " + column.name() + ": missing for most of the normal period");
                continue;
            }
            before = fillShortGaps(before, FILL_LIMIT);
            if (neverMoves(before)) {
                warnings.add("dropped " + column.name() + ": never changes during the normal period");
                continue;
            }
            double[] after = fillShortGaps(column(recent, c), FILL_LIMIT);
            double[] window = new double[windowRows.size()];
            for (int i = 0; i < window.length; i++) {
                window[i] = after[windowRows.get(i)];
            }
            double score = nsigmaScore(before, window);
            scored.add(new IndicatorRanking(column.name(), column.service(), column.metric(), 0,
                    score, score, 0.0));
            // A service is as bad as its worst column; on a tie the first column wins,
            // as Python's max() does.
            Double best = serviceScore.get(column.service());
            if (best == null || score > best) {
                serviceScore.put(column.service(), score);
                serviceTop.put(column.service(), column.name());
            }
        }

        if (windowRows.isEmpty()) {
            warnings.add("the analysis window is empty");
        }
        List<String> order = new ArrayList<>(serviceScore.keySet());
        order.sort(Comparator.comparing((String s) -> -serviceScore.get(s))
                .thenComparing(Comparator.naturalOrder()));

        boolean found = !order.isEmpty() && serviceScore.get(order.get(0)) >= MIN_CAUSE_SCORE;
        String verdict = found ? AnalyzeResponse.ROOT_CAUSE_FOUND : AnalyzeResponse.NO_CLEAR_CAUSE;

        List<ServiceRanking> services = new ArrayList<>();
        for (int i = 0; i < order.size(); i++) {
            String service = order.get(i);
            double score = serviceScore.get(service);
            String role = (i == 0 && found) ? "CAUSE" : score >= ABNORMAL_SCORE ? "ALSO_ABNORMAL" : "NORMAL";
            services.add(new ServiceRanking(service, i + 1, score, score, 0.0,
                    serviceTop.get(service), role, null));
        }

        scored.sort(Comparator.comparing((IndicatorRanking r) -> -r.selfScore())
                .thenComparing(IndicatorRanking::column));
        int topK = topK(request.params());
        List<IndicatorRanking> indicators = new ArrayList<>();
        for (int i = 0; i < Math.min(topK, scored.size()); i++) {
            IndicatorRanking r = scored.get(i);
            indicators.add(new IndicatorRanking(r.column(), r.service(), r.metric(), i + 1,
                    r.selfScore(), r.marginalScore(), 0.0));
        }

        double start = windowRows.isEmpty() ? request.alarmTimeSec() : recentTimes[windowRows.get(0)];
        double end = windowRows.isEmpty() ? request.alarmTimeSec()
                : recentTimes[windowRows.get(windowRows.size() - 1)];
        long tookMs = (System.nanoTime() - started) / 1_000_000;
        return new AnalyzeResponse(request.requestId(), ENGINE_NAME, "java", tookMs, verdict,
                (double) request.alarmTimeSec(), null, start, end, services, indicators, warnings);
    }

    /** {@code |mean(after) - mean(before)| / (std(before) + eps)}; 0 when undefined. */
    static double nsigmaScore(double[] before, double[] after) {
        double centre = nanMean(before);
        double spread = nanStd(before, centre);
        double moved = nanMean(after);
        double eps = EPS_FACTOR * (Math.abs(Double.isNaN(centre) ? 0.0 : centre) + 1.0);
        double score = Math.abs(moved - centre) / (spread + eps);
        return Double.isNaN(score) ? 0.0 : score;
    }

    static double nanMean(double[] values) {
        double sum = 0;
        int n = 0;
        for (double v : values) {
            if (!Double.isNaN(v)) {
                sum += v;
                n++;
            }
        }
        return n == 0 ? Double.NaN : sum / n;
    }

    /** Population standard deviation (numpy's default, ddof = 0), NaN skipped. */
    static double nanStd(double[] values, double mean) {
        double sum = 0;
        int n = 0;
        for (double v : values) {
            if (!Double.isNaN(v)) {
                sum += (v - mean) * (v - mean);
                n++;
            }
        }
        return n == 0 ? Double.NaN : Math.sqrt(sum / n);
    }

    static double nanFraction(double[] values) {
        if (values.length == 0) {
            return 1.0;
        }
        int missing = 0;
        for (double v : values) {
            if (Double.isNaN(v)) {
                missing++;
            }
        }
        return (double) missing / values.length;
    }

    /**
     * Fill runs of missing values no longer than {@code limit}: with the value before
     * the run, or, for a run at the very start, the value after it. Longer runs stay
     * missing - carrying a value across a long gap would invent data.
     */
    static double[] fillShortGaps(double[] series, int limit) {
        double[] out = series.clone();
        int i = 0;
        while (i < out.length) {
            if (!Double.isNaN(out[i])) {
                i++;
                continue;
            }
            int start = i;
            while (i < out.length && Double.isNaN(out[i])) {
                i++;
            }
            int end = i;
            if (end - start > limit) {
                continue;
            }
            if (start > 0) {
                java.util.Arrays.fill(out, start, end, out[start - 1]);
            } else if (end < out.length) {
                java.util.Arrays.fill(out, start, end, out[end]);
            }
        }
        return out;
    }

    /** Flat in the normal period: both the standard deviation and the MAD are zero. */
    static boolean neverMoves(double[] series) {
        double[] usable = java.util.Arrays.stream(series).filter(v -> !Double.isNaN(v)).toArray();
        if (usable.length == 0) {
            return true;
        }
        double mean = nanMean(usable);
        double spread = nanStd(usable, mean);
        double median = median(usable);
        double[] deviations = new double[usable.length];
        for (int i = 0; i < usable.length; i++) {
            deviations[i] = Math.abs(usable[i] - median);
        }
        return spread == 0.0 && median(deviations) == 0.0;
    }

    static double median(double[] values) {
        double[] sorted = values.clone();
        java.util.Arrays.sort(sorted);
        int n = sorted.length;
        return n % 2 == 1 ? sorted[n / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0;
    }

    private static double[] column(double[][] rows, int c) {
        double[] out = new double[rows.length];
        for (int r = 0; r < rows.length; r++) {
            out[r] = rows[r][c];
        }
        return out;
    }

    private static int topK(Map<String, Object> params) {
        if (params != null && params.get("topK") instanceof Number n) {
            return Math.max(1, n.intValue());
        }
        return DEFAULT_TOP_K;
    }
}
