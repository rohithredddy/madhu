package com.xairca.backend.report;

import com.xairca.backend.analyze.AnalyzeResponse;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import com.xairca.backend.explain.Explanation;
import com.xairca.backend.runs.AnalysisRunDto;
import java.util.List;
import java.util.Locale;
import org.springframework.stereotype.Service;

/**
 * Markdown reports of a run (docs/03 section 4.12): headline, sentences, the ranking,
 * the ground truth when there is one, engine and timing. Benchmark reports are built
 * by the benchmark package, which owns that data.
 */
@Service
public class ReportService {

    public String runMarkdown(AnalysisRunDto run) {
        StringBuilder md = new StringBuilder();
        Explanation explanation = run.explanation();
        AnalyzeResponse response = run.response();
        md.append("# Analysis report: ").append(run.caseId()).append("\n\n");
        md.append("- Engine: ").append(run.engine()).append("\n");
        md.append("- Mode: ").append(run.mode()).append(", detection delay ")
                .append(run.delaySeconds()).append(" s\n");
        md.append("- Run: ").append(run.runId()).append(", ").append(run.createdAt())
                .append(", took ").append(run.tookMs()).append(" ms\n");
        md.append("- Verdict: ").append(response.verdict()).append("\n\n");

        md.append("## ").append(explanation.headline()).append("\n\n");
        section(md, "Cause", explanation.causeSentences());
        section(md, "Other services", explanation.symptomSentences());
        section(md, "Evidence", explanation.evidenceSentences());
        section(md, "Notes", explanation.notes());

        md.append("## Ranking\n\n| Rank | Service | Score | Marginal | Inherited | Top indicator | Role |\n");
        md.append("|---|---|---|---|---|---|---|\n");
        for (ServiceRanking s : response.services()) {
            md.append("| ").append(s.rank()).append(" | ").append(s.service()).append(" | ")
                    .append(number(s.score())).append(" | ").append(number(s.marginalScore()))
                    .append(" | ").append(percent(s.inheritedFraction())).append(" | ")
                    .append(s.topIndicator()).append(" | ").append(s.role()).append(" |\n");
        }
        md.append("\n");

        if (run.groundTruth() != null) {
            md.append("## Ground truth\n\n- Service: ").append(run.groundTruth().service()).append("\n");
            md.append("- Indicator: ").append(run.groundTruth().indicator() == null
                    ? "no single right metric for this fault type" : run.groundTruth().indicator())
                    .append("\n");
            if (run.evaluation() != null) {
                md.append("- Rank of the true service: ").append(rank(run.evaluation().rankGtService()))
                        .append("\n- Correct at top 1: ").append(run.evaluation().correctTop1() ? "yes" : "no")
                        .append("\n- Blamed a caller of the culprit (symptom error): ")
                        .append(run.evaluation().symptomError() == null ? "cannot tell, no call graph"
                                : run.evaluation().symptomError() ? "yes" : "no")
                        .append("\n");
            }
            md.append("\n_The ground truth was used only to score this result; the engine never saw it._\n");
        }
        return md.toString();
    }

    private static void section(StringBuilder md, String title, List<String> sentences) {
        if (sentences == null || sentences.isEmpty()) {
            return;
        }
        md.append("### ").append(title).append("\n\n");
        for (String sentence : sentences) {
            md.append("- ").append(sentence).append("\n");
        }
        md.append("\n");
    }

    private static String number(Double value) {
        return value == null ? "" : String.format(Locale.ROOT, "%.2f", value);
    }

    private static String percent(Double value) {
        return value == null ? "" : Math.round(value * 100) + "%";
    }

    private static String rank(Integer rank) {
        return rank == null ? "not ranked" : rank.toString();
    }
}
