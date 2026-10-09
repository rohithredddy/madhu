package com.xairca.backend.replay;

import static org.assertj.core.api.Assertions.assertThat;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.Arrays;
import java.util.Random;
import org.junit.jupiter.api.Test;

class OnlineDetectorTest {

    private static final long T0 = 1_700_000_000L;

    /** Rows of normal noise; a step of +12 sd in column 1 from {@code faultRow}. */
    private static double[][] rows(int n, int faultRow, long seed) {
        Random random = new Random(seed);
        double[][] rows = new double[n][3];
        for (int r = 0; r < n; r++) {
            for (int c = 0; c < 3; c++) {
                rows[r][c] = 10 * (c + 1) + random.nextGaussian();
            }
            if (r >= faultRow) {
                rows[r][1] += 12;
            }
        }
        return rows;
    }

    @Test
    void learnsThenWatchesThenAlarmsJustAfterTheFault() {
        double[][] data = rows(400, 250, 7);
        OnlineDetector detector = new OnlineDetector(3, 200, 3, 0.01);
        Integer alarmRow = null;
        for (int r = 0; r < data.length; r++) {
            detector.push(T0 + r, data[r]);
            if (r == 199) {
                assertThat(detector.state()).isEqualTo(OnlineDetector.State.WATCHING);
                assertThat(detector.threshold()).isPositive();
            }
            if (alarmRow == null && detector.state() == OnlineDetector.State.ALARM) {
                alarmRow = r;
            }
        }
        // Three rows above the threshold in a row: the third faulty row.
        assertThat(alarmRow).isEqualTo(252);
        assertThat(detector.alarmTimeSec()).isEqualTo(T0 + 252);
        assertThat(detector.topColumnsAtAlarm().get(0)).isEqualTo(1);
    }

    @Test
    void staysQuietOnPureNormalData() {
        double[][] data = rows(1500, Integer.MAX_VALUE, 42);
        OnlineDetector detector = new OnlineDetector(3, 300, 3, 0.01);
        for (int r = 0; r < data.length; r++) {
            detector.push(T0 + r, data[r]);
        }
        assertThat(detector.state()).isEqualTo(OnlineDetector.State.WATCHING);
        assertThat(detector.alarmTimeSec()).isNull();
    }

    @Test
    void scoresAreNotComputedWhileLearning() {
        OnlineDetector detector = new OnlineDetector(3, 10, 3, 0.01);
        assertThat(detector.push(T0, new double[] {1, 2, 3})).isNaN();
        assertThat(detector.state()).isEqualTo(OnlineDetector.State.LEARNING);
    }

    /**
     * Hard rule: the detector is never told when the fault was injected. Nothing it
     * can be constructed or fed with is named like an injection time, and its inputs
     * are only counts, settings and rows (docs/03 section 4.7).
     */
    @Test
    void theDetectorIsNeverGivenTheInjectionTime() {
        for (Constructor<?> constructor : OnlineDetector.class.getConstructors()) {
            assertThat(Arrays.stream(constructor.getParameters()).map(Parameter::getName))
                    .noneMatch(name -> name.toLowerCase().contains("inject"));
            assertThat(constructor.getParameterTypes())
                    .containsExactly(int.class, int.class, int.class, double.class);
        }
        for (Method method : OnlineDetector.class.getMethods()) {
            assertThat(method.getName().toLowerCase()).doesNotContain("inject");
        }
    }
}
