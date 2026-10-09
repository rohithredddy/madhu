package com.xairca.backend.cases;

/**
 * One line of the case list (docs/06 section 4).
 *
 * @param replayable whether the injection happens after the replay detector's
 *     baseline rows, so a replay would learn "normal" from normal data. The only use
 *     of the injection time in the catalog (docs/03 section 4.1).
 */
public record CaseSummary(
        String caseId,
        String source,
        String system,
        String faultType,
        String gtService,
        int nRows,
        int nColumns,
        boolean replayable) {}
