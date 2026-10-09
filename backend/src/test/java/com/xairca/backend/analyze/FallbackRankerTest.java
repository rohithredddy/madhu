package com.xairca.backend.analyze;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.TestData;
import com.xairca.backend.analyze.AnalyzeResponse.IndicatorRanking;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import java.io.File;
import org.junit.jupiter.api.Test;

/**
 * The Java fallback must rank exactly as Python's NSIGMA (docs/03 section 4.4).
 *
 * <p>Both sides read the same committed request, and Python's answer to it is
 * committed beside it; Python has a test that fails if that answer drifts from the
 * code, so this cannot end up checking a stale fixture.
 */
class FallbackRankerTest {

    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static <T> T read(String name, Class<T> type) throws Exception {
        return MAPPER.readValue(new File(TestData.SAMPLES.toFile(), name), type);
    }

    @Test
    void ranksTheSharedSampleExactlyLikePythonNsigma() throws Exception {
        AnalyzeRequest request = read("analyze_request.json", AnalyzeRequest.class);
        AnalyzeResponse python = read("analyze_response_nsigma.json", AnalyzeResponse.class);

        AnalyzeResponse java = new FallbackRanker().rank(request);

        assertThat(java.engine()).isEqualTo("NSIGMA_JAVA_FALLBACK");
        assertThat(java.verdict()).isEqualTo(python.verdict());
        assertThat(java.services()).extracting(ServiceRanking::service)
                .containsExactlyElementsOf(python.services().stream().map(ServiceRanking::service).toList());
        for (int i = 0; i < python.services().size(); i++) {
            ServiceRanking p = python.services().get(i);
            ServiceRanking j = java.services().get(i);
            assertThat(j.score()).as(p.service()).isCloseTo(p.score(), within(1e-9));
            assertThat(j.topIndicator()).isEqualTo(p.topIndicator());
            assertThat(j.role()).isEqualTo(p.role());
        }
        assertThat(java.indicators()).extracting(IndicatorRanking::column).containsExactlyElementsOf(
                python.indicators().stream().map(IndicatorRanking::column).toList());
        assertThat(java.windowStartSec()).isEqualTo(python.windowStartSec());
        assertThat(java.windowEndSec()).isEqualTo(python.windowEndSec());
    }

    @Test
    void neverProducesASymptomOrAnInheritedFraction() throws Exception {
        AnalyzeResponse java = new FallbackRanker().rank(read("analyze_request.json", AnalyzeRequest.class));
        assertThat(java.services()).allSatisfy(s -> {
            assertThat(s.role()).isNotEqualTo("SYMPTOM");
            assertThat(s.inheritedFraction()).isZero();
            assertThat(s.explainedBy()).isNull();
            assertThat(s.score()).isEqualTo(s.marginalScore());
        });
        assertThat(java.changePointSec()).isNull();
    }

    @Test
    void shortGapsAreFilledAndLongOnesAreNot() {
        double nan = Double.NaN;
        assertThat(FallbackRanker.fillShortGaps(new double[] {1, nan, nan, 4}, 3))
                .containsExactly(1, 1, 1, 4);
        assertThat(FallbackRanker.fillShortGaps(new double[] {nan, 2, 3}, 3)).containsExactly(2, 2, 3);
        double[] longGap = FallbackRanker.fillShortGaps(new double[] {1, nan, nan, nan, nan, 6}, 3);
        assertThat(longGap[2]).isNaN();
    }

    @Test
    void aFlatColumnNeverMovesButARareJumpDoes() {
        assertThat(FallbackRanker.neverMoves(new double[] {5, 5, 5, 5})).isTrue();
        assertThat(FallbackRanker.neverMoves(new double[] {5, 5, 5, 9})).isFalse();
        assertThat(FallbackRanker.neverMoves(new double[] {Double.NaN})).isTrue();
    }

    @Test
    void nsigmaByHand() {
        // normal mean 2, population std sqrt(2/3); abnormal mean 6.
        double score = FallbackRanker.nsigmaScore(new double[] {1, 2, 3}, new double[] {6, 6});
        assertThat(score).isCloseTo(4 / (Math.sqrt(2.0 / 3) + 1e-6 * 3), within(1e-12));
    }
}
