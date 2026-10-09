package com.xairca.backend.explain;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.TestData;
import com.xairca.backend.analyze.AnalyzeResponse;
import com.xairca.backend.analyze.AnalyzeResponse.IndicatorRanking;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import java.io.File;
import java.util.List;
import org.junit.jupiter.api.Test;

/** Every template, with fixed responses (docs/03 section 4.6). */
class ExplanationRendererTest {

    private final ExplanationRenderer renderer = new ExplanationRenderer();

    private static AnalyzeResponse response(String engine, String verdict, Double changePoint,
                                            List<ServiceRanking> services) {
        List<IndicatorRanking> indicators = List.of(
                new IndicatorRanking("cart_mem", "cart", "mem", 1, 11.2, 11.9, 0.06),
                new IndicatorRanking("front_latency", "front", "latency", 2, 1.4, 8.3, 0.83));
        return new AnalyzeResponse("r", engine, "0.1.0", 10L, verdict, 1_700_000_100.0, changePoint,
                1_700_000_070.0, 1_700_000_190.0, services, indicators, List.of());
    }

    private static final List<ServiceRanking> CAUSE_AND_SYMPTOM = List.of(
            new ServiceRanking("cart", 1, 11.2, 11.9, 0.06, "cart_mem", "CAUSE", null),
            new ServiceRanking("front", 2, 1.4, 8.3, 0.83, "front_latency", "SYMPTOM", "cart"),
            new ServiceRanking("pay", 3, 4.0, 4.0, 0.1, "pay_cpu", "ALSO_ABNORMAL", null));

    @Test
    void headlineCauseSymptomAndEvidence() {
        Explanation e = renderer.render(response("PARE", "ROOT_CAUSE_FOUND", 1_700_000_070.0, CAUSE_AND_SYMPTOM));
        assertThat(e.headline()).isEqualTo("Likely root cause: cart (memory use). Confidence: HIGH.");
        assertThat(e.causeSentences()).containsExactly(
                "cart's memory use moved 11.2 times its normal spread away from normal, starting at "
                        + "22:14:30 UTC. The services it depends on do not explain this change.");
        assertThat(e.symptomSentences()).containsExactly(
                "front also looks abnormal (8.3), but about 83% of this change is explained by cart. "
                        + "It is probably affected, not the cause.",
                "pay is also unusual (4.0) and this is not explained by its dependencies. "
                        + "It may be a second problem.");
        assertThat(e.evidenceSentences()).containsExactly(
                "Alarm at 22:15:00 UTC; the change most likely started at 22:14:30 UTC (30 s earlier).");
    }

    @Test
    void noClearCauseIsNeverAnAccusation() {
        List<ServiceRanking> quiet = List.of(
                new ServiceRanking("cart", 1, 2.1, 2.1, 0.0, "cart_mem", "NORMAL", null),
                new ServiceRanking("front", 2, 1.0, 1.0, 0.0, "front_latency", "NORMAL", null));
        Explanation e = renderer.render(response("PARE", "NO_CLEAR_CAUSE", null, quiet));
        assertThat(e.headline()).isEqualTo("No clear root cause found. The strongest signal is cart (2.1).");
        assertThat(e.confidence()).isEqualTo("LOW");
        assertThat(e.causeSentences()).isEmpty();
    }

    @Test
    void aBaselineIsNotCreditedWithCheckingDependencies() {
        List<ServiceRanking> services = List.of(
                new ServiceRanking("cart", 1, 9.0, 9.0, 0.0, "cart_mem", "CAUSE", null),
                new ServiceRanking("pay", 2, 4.0, 4.0, 0.0, "pay_cpu", "ALSO_ABNORMAL", null));
        Explanation e = renderer.render(response("NSIGMA", "ROOT_CAUSE_FOUND", null, services));
        assertThat(e.causeSentences().get(0))
                .endsWith("This method does not check whether the services it depends on explain it.");
        assertThat(e.symptomSentences().get(0)).isEqualTo("pay is also unusual (4.0). It may be a second problem.");
    }

    @Test
    void aMethodWithItsOwnScaleIsNotDescribedInSpreads() {
        List<ServiceRanking> services = List.of(
                new ServiceRanking("cart", 1, 0.9, 0.9, 0.0, "cart_mem", "NORMAL", null));
        Explanation e = renderer.render(response("SHAP_IFOREST", "ROOT_CAUSE_FOUND", null, services));
        assertThat(e.causeSentences().get(0)).contains("stands out most to this method (score 0.9)")
                .doesNotContain("normal spread");
        assertThat(e.notes()).anyMatch(n -> n.contains("own scale"));
    }

    @Test
    void confidenceBands() {
        assertThat(ExplanationRenderer.confidence(List.of(svc(10), svc(5)))).isEqualTo("HIGH");
        assertThat(ExplanationRenderer.confidence(List.of(svc(10), svc(7)))).isEqualTo("MEDIUM");
        assertThat(ExplanationRenderer.confidence(List.of(svc(10), svc(9)))).isEqualTo("LOW");
        assertThat(ExplanationRenderer.confidence(List.of(svc(10)))).isEqualTo("HIGH");
    }

    @Test
    void metricLabels() {
        assertThat(MetricLabels.label("cpu")).isEqualTo("CPU usage");
        assertThat(MetricLabels.label("latency-90")).isEqualTo("response time (90th percentile)");
        assertThat(MetricLabels.label("workload")).isEqualTo("workload");
    }

    @Test
    void rendersThePythonSampleResponse() throws Exception {
        AnalyzeResponse pare = new ObjectMapper()
                .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false)
                .readValue(new File(TestData.SAMPLES.toFile(), "analyze_response_pare.json"),
                        AnalyzeResponse.class);
        Explanation e = renderer.render(pare);
        assertThat(e.headline()).startsWith("Likely root cause: " + pare.services().get(0).service());
        assertThat(e.symptomSentences()).anyMatch(s -> s.contains("is probably affected, not the cause"));
    }

    private static ServiceRanking svc(double score) {
        return new ServiceRanking("s" + score, 1, score, score, 0.0, "x_cpu", "NORMAL", null);
    }
}
