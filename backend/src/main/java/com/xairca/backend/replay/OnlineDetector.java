package com.xairca.backend.replay;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
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
 * what makes the false-alarm promise hold.
 */
public final class OnlineDetector {

    public enum State { LEARNING, WATCHING, ALARM }

    private final int nColumns;
    private final int baselineRows;
    private final int consecutiveRows;
    private final double alpha;
    private final List<double[]> baseline = new ArrayList<>();

    private State state = State.LEARNING;
    private RobustStats stats;
    private ConformalThreshold threshold;
    private int above;
    private Long alarmTimeSec;
    private List<Integer> topColumnsAtAlarm = List.of();

    public OnlineDetector(int nColumns, int baselineRows, int consecutiveRows, double alpha) {
        if (baselineRows < 4) {
            throw new IllegalArgumentException("need at least 4 baseline rows");
        }
        this.nColumns = nColumns;
        this.baselineRows = baselineRows;
        this.consecutiveRows = consecutiveRows;
        this.alpha = alpha;
    }

    /**
     * Feed one row. Returns its score, or NaN while still learning.
     *
     * @param timeSec when the row was recorded; kept only to report the alarm time
     */
    public double push(long timeSec, double[] row) {
        if (state == State.LEARNING) {
            baseline.add(row.clone());
            if (baseline.size() == baselineRows) {
                calibrate();
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
            }
        }
        return score;
    }

    private void calibrate() {
        int half = baseline.size() / 2;
        double[][] first = baseline.subList(0, half).toArray(new double[0][]);
        stats = RobustStats.of(first, nColumns);
        double[] scores = new double[baseline.size() - half];
        for (int i = half; i < baseline.size(); i++) {
            scores[i - half] = stats.rowScore(baseline.get(i));
        }
        threshold = ConformalThreshold.of(scores, alpha);
        state = State.WATCHING;
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

    /** z of one value against the baseline, NaN while learning. */
    public double z(int column, double value) {
        return stats == null ? Double.NaN : stats.z(column, value);
    }
}
