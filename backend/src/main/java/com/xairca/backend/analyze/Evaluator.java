package com.xairca.backend.analyze;

import com.xairca.backend.analyze.AnalyzeResponse.IndicatorRanking;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import com.xairca.backend.cases.CallGraph;
import com.xairca.backend.cases.GroundTruth;
import com.xairca.backend.runs.AnalysisRunDto.Evaluation;
import java.util.List;

/**
 * Compares an engine's answer with the ground truth, after the engine has answered.
 * This is the only place on the Java side that reads the answer (hard rule 4).
 *
 * <p>Same definitions as pare/eval_metrics.py: the rank is the position in the
 * order the engine returned, and a symptom error is a wrong top-1 that calls the true
 * root cause, directly or indirectly (docs/06 section 5). Without a call graph the
 * symptom question cannot be asked, so it is null rather than false.
 */
public final class Evaluator {

    private Evaluator() {}

    /** Null when the case has no ground truth (an upload without one). */
    public static Evaluation evaluate(AnalyzeResponse response, GroundTruth truth, CallGraph graph) {
        if (truth == null || truth.service() == null) {
            return null;
        }
        Integer serviceRank = serviceRank(response.services(), truth.service());
        Integer indicatorRank = truth.indicator() == null ? null
                : indicatorRank(response.indicators(), truth.indicator());
        boolean top1 = serviceRank != null && serviceRank == 1;
        boolean top3 = serviceRank != null && serviceRank <= 3;
        Boolean symptom = null;
        if (graph != null && !graph.isEmpty() && !response.services().isEmpty()) {
            String first = response.services().get(0).service();
            symptom = !first.equals(truth.service()) && graph.ancestors(truth.service()).contains(first);
        }
        return new Evaluation(serviceRank, indicatorRank, top1, top3, symptom);
    }

    static Integer serviceRank(List<ServiceRanking> services, String service) {
        for (int i = 0; i < services.size(); i++) {
            if (services.get(i).service().equals(service)) {
                return i + 1;
            }
        }
        return null;
    }

    static Integer indicatorRank(List<IndicatorRanking> indicators, String column) {
        for (int i = 0; i < indicators.size(); i++) {
            if (indicators.get(i).column().equals(column)) {
                return i + 1;
            }
        }
        return null;
    }
}
