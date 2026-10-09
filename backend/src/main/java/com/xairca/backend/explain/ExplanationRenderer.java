package com.xairca.backend.explain;

import com.xairca.backend.analyze.AnalyzeResponse;
import com.xairca.backend.analyze.AnalyzeResponse.IndicatorRanking;
import com.xairca.backend.analyze.AnalyzeResponse.ServiceRanking;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Turns an engine's answer into sentences a person can act on (docs/03 section 4.6).
 *
 * <p>Template-based on purpose: every sentence can be traced to a number in the
 * response, and nothing is invented. Numbers have one decimal. Two rules keep the
 * text honest, and both have tests:
 * <ul>
 *   <li>When the verdict is NO_CLEAR_CAUSE the headline says so, confidence is LOW
 *       and there are no cause sentences: a quiet window must not read as an
 *       accusation.</li>
 *   <li>"The services it depends on do not explain this change" is said only by an
 *       engine that checked - the residual-based PARE variants. A baseline that never
 *       looked at the call graph is not credited with a claim it cannot make.</li>
 * </ul>
 */
@Component
public class ExplanationRenderer {

    /** Engines whose scores are "times the normal spread", so that wording is true. */
    static final Set<String> SPREAD_SCORED = Set.of(
            "PARE", "PARE_NO_RESIDUAL", "PARE_NO_CP", "PARE_LGBM", "NSIGMA", "NSIGMA_JAVA_FALLBACK");

    /** Engines that subtract what a service's callees explain (the residual step). */
    static final Set<String> RESIDUAL_BASED = Set.of("PARE", "PARE_NO_CP", "PARE_LGBM");

    private static final DateTimeFormatter TIME =
            DateTimeFormatter.ofPattern("HH:mm:ss").withZone(ZoneOffset.UTC);

    public Explanation render(AnalyzeResponse response) {
        List<ServiceRanking> services = response.services();
        List<String> cause = new ArrayList<>();
        List<String> symptom = new ArrayList<>();
        List<String> evidence = new ArrayList<>();
        List<String> notes = new ArrayList<>();
        boolean spread = SPREAD_SCORED.contains(response.engine());
        boolean residual = RESIDUAL_BASED.contains(response.engine());

        if (services.isEmpty()) {
            notes.addAll(response.warnings());
            return new Explanation("No result: nothing in this window could be scored.", "LOW",
                    cause, symptom, evidence, notes);
        }

        ServiceRanking top = services.get(0);
        boolean found = AnalyzeResponse.ROOT_CAUSE_FOUND.equals(response.verdict());
        String headline;
        String confidence;
        if (found) {
            confidence = confidence(services);
            headline = "Likely root cause: " + top.service() + " ("
                    + MetricLabels.label(metricOf(response, top.topIndicator())) + "). Confidence: "
                    + confidence + ".";
            cause.add(causeSentence(response, top, spread, residual));
        } else {
            confidence = "LOW";
            headline = "No clear root cause found. The strongest signal is " + top.service()
                    + " (" + one(top.score()) + ").";
        }

        for (ServiceRanking s : services) {
            if ("SYMPTOM".equals(s.role())) {
                symptom.add(s.service() + " also looks abnormal (" + one(s.marginalScore())
                        + "), but about " + Math.round(100 * value(s.inheritedFraction()))
                        + "% of this change is explained by "
                        + (s.explainedBy() == null ? "the services it calls" : s.explainedBy())
                        + ". It is probably affected, not the cause.");
            } else if ("ALSO_ABNORMAL".equals(s.role())) {
                symptom.add(s.service() + " is also unusual (" + one(s.marginalScore()) + ")"
                        + (residual ? " and this is not explained by its dependencies" : "")
                        + ". It may be a second problem.");
            }
        }

        evidence.add(evidenceSentence(response));
        for (String warning : response.warnings()) {
            notes.add(plain(warning));
        }
        if (!spread) {
            notes.add("Scores from " + response.engine() + " are on that method's own scale, not"
                    + " in units of normal spread, so compare them within this run only.");
        }
        return new Explanation(headline, confidence, cause, symptom, evidence, notes);
    }

    /** HIGH if the top score is at least twice the second, MEDIUM if 1.3 times, else LOW. */
    static String confidence(List<ServiceRanking> services) {
        double first = value(services.get(0).score());
        double second = services.size() > 1 ? value(services.get(1).score()) : 0.0;
        if (second <= 0 || first >= 2.0 * second) {
            return "HIGH";
        }
        return first >= 1.3 * second ? "MEDIUM" : "LOW";
    }

    private static String causeSentence(AnalyzeResponse response, ServiceRanking top,
                                        boolean spread, boolean residual) {
        String metric = MetricLabels.label(metricOf(response, top.topIndicator()));
        String when = response.changePointSec() != null
                ? ", starting at " + time(response.changePointSec())
                : "";
        String moved = spread
                ? " moved " + one(top.score()) + " times its normal spread away from normal"
                : " stands out most to this method (score " + one(top.score()) + ")";
        String why = residual
                ? " The services it depends on do not explain this change."
                : " This method does not check whether the services it depends on explain it.";
        return top.service() + "'s " + metric + moved + when + "." + why;
    }

    private static String evidenceSentence(AnalyzeResponse response) {
        String alarm = "Alarm at " + time(response.alarmTimeSec());
        if (response.changePointSec() != null && response.alarmTimeSec() != null) {
            long earlier = Math.round(response.alarmTimeSec() - response.changePointSec());
            return alarm + "; the change most likely started at " + time(response.changePointSec())
                    + " (" + earlier + " s earlier).";
        }
        return alarm + "; the data from " + time(response.windowStartSec()) + " to "
                + time(response.windowEndSec()) + " was compared with normal behaviour.";
    }

    private static String metricOf(AnalyzeResponse response, String column) {
        for (IndicatorRanking indicator : response.indicators()) {
            if (indicator.column().equals(column)) {
                return indicator.metric();
            }
        }
        // Not in the returned top-k: fall back to the part after the last underscore,
        // for display only. Nothing is computed from it.
        return column == null ? null : column.substring(column.lastIndexOf('_') + 1);
    }

    /** Engine warnings, in plain words where a known phrasing can be made plainer. */
    private static String plain(String warning) {
        return warning.substring(0, 1).toUpperCase(Locale.ROOT) + warning.substring(1)
                + (warning.endsWith(".") ? "" : ".");
    }

    static String one(Double value) {
        return value == null ? "n/a" : String.format(Locale.ROOT, "%.1f", value);
    }

    private static double value(Double value) {
        return value == null || value.isNaN() ? 0.0 : value;
    }

    static String time(Double epochSeconds) {
        return epochSeconds == null ? "an unknown time"
                : TIME.format(Instant.ofEpochSecond(Math.round(epochSeconds))) + " UTC";
    }
}
