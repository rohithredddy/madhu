package com.xairca.backend.replay;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import org.junit.jupiter.api.Test;

/** Hand-computed values; the same rules as pare.scores.robust_baseline. */
class RobustStatsTest {

    @Test
    void medianAndMadByHand() {
        // 1..5: median 3, absolute deviations 2,1,0,1,2 -> MAD 1.
        RobustStats stats = RobustStats.of(column(1, 2, 3, 4, 5), 1);
        assertThat(stats.median(0)).isEqualTo(3.0);
        assertThat(stats.scale(0)).isCloseTo(1.4826 + 1e-6 * 4, within(1e-12));
        assertThat(stats.z(0, 5)).isCloseTo(2 / (1.4826 + 4e-6), within(1e-9));
    }

    @Test
    void aColumnFlatInItsMiddleFallsBackToTheStandardDeviation() {
        // MAD is 0 (most values equal) but the column is not constant: decision 72.
        RobustStats stats = RobustStats.of(column(5, 5, 5, 5, 5, 9), 1);
        double std = RobustStats.std(new double[] {5, 5, 5, 5, 5, 9});
        assertThat(stats.usable(0)).isTrue();
        assertThat(stats.scale(0)).isCloseTo(std + 1e-6 * 6, within(1e-12));
        assertThat(stats.z(0, 9)).isLessThan(10); // not the millions the epsilon alone would give
    }

    @Test
    void aConstantColumnIsSkipped() {
        RobustStats stats = RobustStats.of(column(7, 7, 7), 1);
        assertThat(stats.usable(0)).isFalse();
        assertThat(stats.z(0, 100)).isNaN();
        assertThat(stats.rowScore(new double[] {100})).isZero();
    }

    @Test
    void missingValuesAreSkipped() {
        RobustStats stats = RobustStats.of(column(1, Double.NaN, 3, 5), 1);
        assertThat(stats.median(0)).isEqualTo(3.0);
        assertThat(stats.z(0, Double.NaN)).isNaN();
    }

    @Test
    void rowScoreIsTheLargestZ() {
        double[][] rows = {{1, 10}, {2, 20}, {3, 30}, {4, 40}, {5, 50}};
        RobustStats stats = RobustStats.of(rows, 2);
        assertThat(stats.rowScore(new double[] {3, 70})).isCloseTo(stats.z(1, 70), within(1e-12));
    }

    private static double[][] column(double... values) {
        double[][] rows = new double[values.length][1];
        for (int i = 0; i < values.length; i++) {
            rows[i][0] = values[i];
        }
        return rows;
    }
}
