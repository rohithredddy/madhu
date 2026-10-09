package com.xairca.backend.replay;

import java.util.Arrays;

/**
 * The alarm threshold, chosen from normal data so that false alarms stay below a
 * target rate (split conformal calibration, docs/00 section 6 step 3).
 *
 * <p>Given n row scores from held-out normal data and a target false-alarm rate
 * alpha, the threshold is the k-th smallest score with
 * {@code k = ceil((n + 1)(1 - alpha))}. If the scores are exchangeable with future
 * normal scores, a new normal row exceeds it with probability at most alpha. When
 * k > n there are too few calibration rows to promise that rate, and the largest
 * score is used - the most cautious threshold the data can give; {@link #exact()}
 * says when this happened.
 */
public final class ConformalThreshold {

    private final double value;
    private final boolean exact;

    private ConformalThreshold(double value, boolean exact) {
        this.value = value;
        this.exact = exact;
    }

    public static ConformalThreshold of(double[] calibrationScores, double alpha) {
        if (calibrationScores.length == 0) {
            throw new IllegalArgumentException("cannot calibrate a threshold from no rows");
        }
        if (alpha <= 0 || alpha >= 1) {
            throw new IllegalArgumentException("alpha must be in (0, 1), got " + alpha);
        }
        double[] sorted = calibrationScores.clone();
        Arrays.sort(sorted);
        int n = sorted.length;
        int k = (int) Math.ceil((n + 1) * (1.0 - alpha));
        if (k > n) {
            return new ConformalThreshold(sorted[n - 1], false);
        }
        return new ConformalThreshold(sorted[k - 1], true);
    }

    public double value() {
        return value;
    }

    /** False when there were too few calibration rows for the promised rate. */
    public boolean exact() {
        return exact;
    }
}
