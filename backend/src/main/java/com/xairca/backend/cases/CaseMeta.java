package com.xairca.backend.cases;

import java.util.List;

/** The contents of a case's meta.json (docs/06 section 2). */
public record CaseMeta(
        String caseId,
        String source,
        String system,
        String faultType,
        long injectTimeSec,
        GroundTruth groundTruth,
        List<ColumnInfo> columns,
        CallGraph graph,
        String notes) {

    public CaseMeta {
        columns = columns == null ? List.of() : List.copyOf(columns);
        graph = graph == null ? CallGraph.empty() : graph;
    }
}
