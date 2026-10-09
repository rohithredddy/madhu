package com.xairca.backend.explain;

import java.util.List;

/**
 * The plain-language explanation of one analysis (docs/06 section 4, AnalysisRun).
 *
 * @param confidence HIGH, MEDIUM or LOW; always LOW when no clear cause was found
 */
public record Explanation(
        String headline,
        String confidence,
        List<String> causeSentences,
        List<String> symptomSentences,
        List<String> evidenceSentences,
        List<String> notes) {}
