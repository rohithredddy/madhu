package com.xairca.backend.replay;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class ConformalThresholdTest {

    @Test
    void theKthSmallestScore() {
        // n = 99 scores 1..99, alpha = 0.1: k = ceil(100 * 0.9) = 90 -> the 90th smallest.
        double[] scores = new double[99];
        for (int i = 0; i < 99; i++) {
            scores[i] = 99 - i;
        }
        ConformalThreshold t = ConformalThreshold.of(scores, 0.1);
        assertThat(t.value()).isEqualTo(90.0);
        assertThat(t.exact()).isTrue();
    }

    @Test
    void tooFewRowsForTheRateGivesTheMaximumAndSaysSo() {
        // n = 50, alpha = 0.01: k = ceil(51 * 0.99) = 51 > 50.
        double[] scores = new double[50];
        for (int i = 0; i < 50; i++) {
            scores[i] = i;
        }
        ConformalThreshold t = ConformalThreshold.of(scores, 0.01);
        assertThat(t.value()).isEqualTo(49.0);
        assertThat(t.exact()).isFalse();
    }

    @Test
    void refusesNothingToCalibrateOn() {
        assertThatThrownBy(() -> ConformalThreshold.of(new double[0], 0.01))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
