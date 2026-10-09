package com.xairca.backend.benchmark;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import java.util.Arrays;
import java.util.List;
import org.junit.jupiter.api.Test;

/** The same hand-worked values as analyzer/tests/test_eval_metrics.py. */
class AccuracyCalculatorTest {

    @Test
    void acAtKAndAvg5ByHand() {
        List<Integer> ranks = Arrays.asList(1, 1, 2, 5, null);
        assertThat(AccuracyCalculator.acAtK(ranks, 1)).isEqualTo(2.0 / 5);
        assertThat(AccuracyCalculator.acAtK(ranks, 3)).isEqualTo(3.0 / 5);
        assertThat(AccuracyCalculator.avgAt5(List.of(5))).isCloseTo(0.2, within(1e-12));
    }

    @Test
    void symptomRateDividesByTheJudgedWrongAnswersOnly() {
        // Right on 100 cases, wrong on 4, one of them by blaming a caller: 0.25, not 0.01.
        List<AccuracyCalculator.Result> results = new java.util.ArrayList<>();
        for (int i = 0; i < 100; i++) {
            results.add(result(1, false));
        }
        results.add(result(2, false));
        results.add(result(3, false));
        results.add(result(4, false));
        results.add(result(5, true));
        assertThat(AccuracyCalculator.symptomRate(results)).isEqualTo(0.25);
    }

    @Test
    void symptomRateIsNullWithoutAGraphOrWithoutErrors() {
        assertThat(AccuracyCalculator.symptomRate(List.of(result(1, false)))).isNull();
        assertThat(AccuracyCalculator.symptomRate(List.of(result(3, null)))).isNull();
    }

    @Test
    void summaryPerEngineAndDelayWithStrictIndicatorCases() {
        List<AccuracyCalculator.Result> results = List.of(
                new AccuracyCalculator.Result("PARE", 0, 1, 1, true, false, "ROOT_CAUSE_FOUND", 100),
                new AccuracyCalculator.Result("PARE", 0, 2, null, false, true, "NO_CLEAR_CAUSE", 300),
                new AccuracyCalculator.Result("NSIGMA", 0, 1, 2, true, false, "ROOT_CAUSE_FOUND", 10));
        List<BenchmarkSummary.Row> rows = new AccuracyCalculator().summarise(results);
        BenchmarkSummary.Row pare = rows.stream().filter(r -> r.engine().equals("PARE")).findFirst().orElseThrow();
        assertThat(pare.cases()).isEqualTo(2);
        assertThat(pare.ac1()).isEqualTo(0.5);
        assertThat(pare.expCases()).isEqualTo(1);
        assertThat(pare.expAc1()).isEqualTo(1.0);
        assertThat(pare.symptomRate()).isEqualTo(1.0);
        assertThat(pare.noClearCause()).isEqualTo(1);
        assertThat(pare.meanMs()).isEqualTo(200.0);
    }

    private static AccuracyCalculator.Result result(Integer rank, Boolean symptom) {
        return new AccuracyCalculator.Result("PARE", 0, rank, null, false, symptom, "ROOT_CAUSE_FOUND", 1);
    }
}
