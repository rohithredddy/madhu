package com.xairca.backend.replay;

import java.util.Arrays;

/**
 * Median and robust scale of each column of a block of rows - the Java twin of
 * {@code pare.scores.robust_baseline}, with the same rules (docs/05 section 3 step 1):
 *
 * <ul>
 *   <li>scale = 1.4826 x MAD + eps, with eps = 1e-6 x (|median| + 1);</li>
 *   <li><b>zero-MAD rule:</b> when the MAD is 0 but the column is not constant, the
 *       standard deviation replaces 1.4826 x MAD. Otherwise a column flat over most of
 *       the baseline gets a scale of about 1e-6 and one ordinary wobble scores in the
 *       millions (decision 72, and docs/03 section 4.7);</li>
 *   <li>a <b>constant</b> column (MAD and std both 0) is marked unusable: it has no
 *       spread to measure a change against. Python's step 0 drops such a column; the
 *       detector skips it.</li>
 * </ul>
 * Missing values (NaN) are skipped everywhere.
 */
public final class RobustStats {

    public static final double MAD_TO_SIGMA = 1.4826;
    public static final double EPS_FACTOR = 1e-6;

    private final double[] median;
    private final double[] scale;
    private final boolean[] usable;

    private RobustStats(double[] median, double[] scale, boolean[] usable) {
        this.median = median;
        this.scale = scale;
        this.usable = usable;
    }

    /** Measure every column of {@code rows} (row-major). */
    public static RobustStats of(double[][] rows, int nColumns) {
        double[] median = new double[nColumns];
        double[] scale = new double[nColumns];
        boolean[] usable = new boolean[nColumns];
        for (int c = 0; c < nColumns; c++) {
            double[] column = present(rows, c);
            if (column.length == 0) {
                continue; // nothing seen: unusable
            }
            double med = median(column);
            double[] deviations = new double[column.length];
            for (int i = 0; i < column.length; i++) {
                deviations[i] = Math.abs(column[i] - med);
            }
            double mad = median(deviations);
            double spread = MAD_TO_SIGMA * mad;
            if (mad == 0.0) {
                spread = std(column);
            }
            median[c] = med;
            usable[c] = spread > 0.0;
            scale[c] = spread + EPS_FACTOR * (Math.abs(med) + 1.0);
        }
        return new RobustStats(median, scale, usable);
    }

    /** |x - median| / scale for one value; NaN for a missing value or unusable column. */
    public double z(int column, double value) {
        if (!usable[column] || Double.isNaN(value)) {
            return Double.NaN;
        }
        return Math.abs(value - median[column]) / scale[column];
    }

    /** Row score = the largest z over the usable columns; 0 when none can be scored. */
    public double rowScore(double[] row) {
        double best = 0.0;
        for (int c = 0; c < row.length; c++) {
            double z = z(c, row[c]);
            if (!Double.isNaN(z) && z > best) {
                best = z;
            }
        }
        return best;
    }

    public double median(int column) {
        return median[column];
    }

    public double scale(int column) {
        return scale[column];
    }

    public boolean usable(int column) {
        return usable[column];
    }

    static double median(double[] values) {
        double[] sorted = values.clone();
        Arrays.sort(sorted);
        int n = sorted.length;
        return n % 2 == 1 ? sorted[n / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0;
    }

    /** Population standard deviation, as numpy's default. */
    static double std(double[] values) {
        double mean = 0;
        for (double v : values) {
            mean += v;
        }
        mean /= values.length;
        double sum = 0;
        for (double v : values) {
            sum += (v - mean) * (v - mean);
        }
        return Math.sqrt(sum / values.length);
    }

    private static double[] present(double[][] rows, int c) {
        return Arrays.stream(rows).mapToDouble(row -> row[c]).filter(v -> !Double.isNaN(v)).toArray();
    }
}
