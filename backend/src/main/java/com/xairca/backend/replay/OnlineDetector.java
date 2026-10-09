package com.xairca.backend.replay;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Deque;
import java.util.List;

/**
 * The live anomaly detector used in replay (docs/03 section 4.7).
 *
 * <p><b>It never looks at the injection time.</b> A real detector does not know when
 * a fault will happen, so this one is not even given it: there is no constructor
 * argument for it, and a test checks that. The alarm the audience sees is produced
 * without any knowledge of the answer.
 *
 * <p>Row by row:
 * <ol>
 *   <li>LEARNING: the first {@code baselineRows} rows are collected.</li>
 *   <li>Then the baseline is split in two halves. The first half gives each column's
 *       median and scale ({@link RobustStats}); the second half, scored with them,
 *       calibrates the threshold ({@link ConformalThreshold}). State WATCHING.</li>
 *   <li>Row score = the largest {@code |x - median| / scale} over the columns.</li>
 *   <li>After {@code consecutiveRows} rows in a row above the threshold: ALARM, with
 *       the alarm time and the five columns that stood out most in that row.</li>
 * </ol>
 * Scoring with the same first-half statistics that the threshold was calibrated on is
 * what makes the false-alarm promise hold - for data that stays like the baseline.
 *
 * <p><b>Rolling baseline (decision 83).</b> Real metrics drift, and a fixed 300-row
 * baseline then raises false alarms long before any fault: measured over 24 replays,
 * 11 alarms came early, up to 287 s before the injection. With
 * {@code recalibrateEveryRows > 0}, every that many rows, and only while no alarm is
 * building, the statistics and threshold are re-learned from the {@code baselineRows}
 * rows that ended {@code gapRows} rows ago. Slow drift is followed; a sudden change is
 * inside the gap and cannot be absorbed before it fires. 0 keeps the fixed baseline of
 * the original spec. Neither mode uses the injection time.
 */
public final class OnlineDetector {

    public enum State { LEARNING, WATCHING, ALARM }

    private final int nColumns;
    private final int baselineRows;
    private final int consecutiveRows;
    private final double alpha;
    private final int recalibrateEveryRows;
    private final int gapRows;
    private final Deque<double[]> history = new ArrayDeque<>();

    private State state = State.LEARNING;
    private RobustStats stats;
    private ConformalThreshold threshold;
    private int above;
    private int seen;
    private int sinceCalibration;
    private Long alarmTimeSec;
    private List<Integer> topColumnsAtAlarm = List.of();

    /** The detector of the original spec: a fixed baseline from the first rows. */
    public OnlineDetector(int nColumns, int baselineRows, int consecutiveRows, double alpha) {
        this(nColumns, baselineRows, consecutiveRows, alpha, 0, 0);
    }

    public OnlineDetector(int nColumns, int baselineRows, int consecutiveRows, double alpha,
                          int recalibrateEveryRows, int gapRows) {
        if (baselineRows < 4) {
            throw new IllegalArgumentException("need at least 4 baseline rows");
        }
        this.nColumns = nColumns;
        this.baselineRows = baselineRows;
        this.consecutiveRows = consecutiveRows;
        this.alpha = alpha;
        this.recalibrateEveryRows = Math.max(0, recalibrateEveryRows);
        this.gapRows = Math.max(0, gapRows);
    }

    /**
     * Feed one row. Returns its score, or NaN while still learning.
     *
     * @param timeSec when the row was recorded; kept only to report the alarm time
     */
    public double push(long timeSec, double[] row) {
        remember(row);
        if (state == State.LEARNING) {
            if (seen == baselineRows) {
                calibrate(new ArrayList<>(history).subList(history.size() - baselineRows, history.size()));
            }
            return Double.NaN;
        }
        double score = stats.rowScore(row);
        if (state == State.WATCHING) {
            above = score > threshold.value() ? above + 1 : 0;
            if (above >= consecutiveRows) {
                state = State.ALARM;
                alarmTimeSec = timeSec;
                topColumnsAtAlarm = topColumns(row, 5);
            } else {
                maybeRecalibrate();
            }
        }
        return score;
    }

    private void remember(double[] row) {
        history.addLast(row.clone());
        seen++;
        int keep = baselineRows + gapRows;
        while (history.size() > keep) {
            history.removeFirst();
        }
    }

    /** Re-learn from the rows that ended {@code gapRows} ago, if it is time and calm. */
    private void maybeRecalibrate() {
        if (recalibrateEveryRows == 0) {
            return;
        }
        sinceCalibration++;
        if (sinceCalibration < recalibrateEveryRows || above > 0 || history.size() < baselineRows + gapRows) {
            return;
        }
        List<double[]> rows = new ArrayList<>(history);
        calibrate(rows.subList(0, baselineRows));
    }

    private void calibrate(List<double[]> baseline) {
        int half = baseline.size() / 2;
        double[][] first = baseline.subList(0, half).toArray(new double[0][]);
        RobustStats calibrationStats = RobustStats.of(first, nColumns);
        double[] scores = new double[baseline.size() - half];
        for (int i = half; i < baseline.size(); i++) {
            scores[i - half] = calibrationStats.rowScore(baseline.get(i));
        }
        threshold = ConformalThreshold.of(scores, alpha);
        // Fixed baseline (the spec): score live rows with the same first-half
        // statistics the threshold was calibrated on. Rolling: the calibration rows
        // were scored against statistics 0.5 to 1.5 half-windows older than
        // themselves, so live rows are scored against the newer half, which keeps
        // them about as far from their statistics (gap + a quarter window) as the
        // calibration rows were. Without this, under drift every live row is further
        // from its statistics than any calibration row, and the alarm fires early.
        stats = recalibrateEveryRows == 0 ? calibrationStats
                : RobustStats.of(baseline.subList(half, baseline.size()).toArray(new double[0][]), nColumns);
        state = State.WATCHING;
        sinceCalibration = 0;
    }

    /** The columns with the largest z in this row, most unusual first. */
    public List<Integer> topColumns(double[] row, int k) {
        if (stats == null) {
            return List.of();
        }
        Integer[] order = new Integer[nColumns];
        for (int c = 0; c < nColumns; c++) {
            order[c] = c;
        }
        Arrays.sort(order, Comparator.comparingDouble((Integer c) -> {
            double z = stats.z(c, row[c]);
            return Double.isNaN(z) ? Double.NEGATIVE_INFINITY : -z;
        }));
        List<Integer> out = new ArrayList<>();
        for (int i = 0; i < Math.min(k, nColumns); i++) {
            if (!Double.isNaN(stats.z(order[i], row[order[i]]))) {
                out.add(order[i]);
            }
        }
        return out;
    }

    public State state() {
        return state;
    }

    /** The threshold, or null while learning. */
    public Double threshold() {
        return threshold == null ? null : threshold.value();
    }

    public Long alarmTimeSec() {
        return alarmTimeSec;
    }

    public List<Integer> topColumnsAtAlarm() {
        return topColumnsAtAlarm;
    }

    /** z of one value against the current baseline, NaN while learning. */
    public double z(int column, double value) {
        return stats == null ? Double.NaN : stats.z(column, value);
    }
}
