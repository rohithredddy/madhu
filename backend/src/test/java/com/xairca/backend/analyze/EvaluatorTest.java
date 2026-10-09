package com.xairca.backend.analyze;

import static org.assertj.core.api.Assertions.assertThat;

import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import com.xairca.backend.cases.CallGraph;
import com.xairca.backend.cases.Edge;
import com.xairca.backend.cases.GroundTruth;
import com.xairca.backend.runs.AnalysisRunDto.Evaluation;
import java.util.List;
import org.junit.jupiter.api.Test;

class EvaluatorTest {

    private static final CallGraph CHAIN = new CallGraph("USER",
            List.of(new Edge("front", "mid"), new Edge("mid", "db"), new Edge("front", "other")));

    private static AnalyzeResponse ranked(String... services) {
        List<ServiceRanking> list = new java.util.ArrayList<>();
        for (int i = 0; i < services.length; i++) {
            list.add(new ServiceRanking(services[i], i + 1, 5.0 - i, 5.0 - i, 0.0, services[i] + "_cpu",
                    "NORMAL", null));
        }
        return new AnalyzeResponse("r", "PARE", "v", 1L, "ROOT_CAUSE_FOUND", 0.0, null, 0.0, 0.0, list,
                List.of(), List.of());
    }

    @Test
    void aRightAnswer() {
        Evaluation e = Evaluator.evaluate(ranked("db", "mid"), new GroundTruth("db", null), CHAIN);
        assertThat(e.rankGtService()).isEqualTo(1);
        assertThat(e.correctTop1()).isTrue();
        assertThat(e.symptomError()).isFalse();
    }

    @Test
    void blamingACallerIsASymptomError() {
        Evaluation e = Evaluator.evaluate(ranked("front", "mid", "db"), new GroundTruth("db", null), CHAIN);
        assertThat(e.rankGtService()).isEqualTo(3);
        assertThat(e.correctTop1()).isFalse();
        assertThat(e.correctTop3()).isTrue();
        assertThat(e.symptomError()).isTrue();
    }

    @Test
    void blamingAnUnrelatedServiceIsWrongButNotASymptomError() {
        Evaluation e = Evaluator.evaluate(ranked("other", "db"), new GroundTruth("db", null), CHAIN);
        assertThat(e.symptomError()).isFalse();
    }

    @Test
    void withoutAGraphTheSymptomQuestionCannotBeAsked() {
        Evaluation e = Evaluator.evaluate(ranked("front"), new GroundTruth("db", null), CallGraph.empty());
        assertThat(e.symptomError()).isNull();
        assertThat(e.rankGtService()).isNull();
    }

    @Test
    void noGroundTruthNoEvaluation() {
        assertThat(Evaluator.evaluate(ranked("db"), null, CHAIN)).isNull();
    }
}
