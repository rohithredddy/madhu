package com.xairca.backend.upload;

import com.xairca.backend.cases.ColumnInfo;
import com.xairca.backend.cases.Edge;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import org.springframework.stereotype.Component;

/**
 * Checks an upload before it becomes a case (docs/03 section 4.11). Returns every
 * problem, not just the first, so the user can fix them all in one go.
 *
 * <ul>
 *   <li>a {@code time} column exists and strictly increases;</li>
 *   <li>every column in the column map exists in the CSV;</li>
 *   <li>every service named by the call graph has at least one column;</li>
 *   <li>at least 60 rows come before the injection time, so there is a normal
 *       period to learn from.</li>
 * </ul>
 */
@Component
public class UploadValidator {

    public static final int MIN_NORMAL_ROWS = 60;

    public List<String> validate(ParsedCsv csv, List<ColumnInfo> columns, List<Edge> edges,
                                 long injectTimeSec, String gtService, String gtIndicator) {
        List<String> problems = new ArrayList<>();
        if (csv.timeSec() == null) {
            problems.add("the CSV needs a column called \"time\" (epoch seconds)");
            return problems;
        }
        for (int r = 1; r < csv.timeSec().length; r++) {
            if (csv.timeSec()[r] <= csv.timeSec()[r - 1]) {
                problems.add("time must increase on every row; row " + (r + 1) + " does not");
                break;
            }
        }
        if (columns == null || columns.isEmpty()) {
            problems.add("the column map is empty");
        } else {
            Set<String> names = new HashSet<>();
            for (ColumnInfo column : columns) {
                if (!csv.header().contains(column.name())) {
                    problems.add("column \"" + column.name() + "\" is not in the CSV");
                }
                if (blank(column.service()) || blank(column.metric())) {
                    problems.add("column \"" + column.name() + "\" needs a service and a metric");
                }
                if (!names.add(column.name())) {
                    problems.add("column \"" + column.name() + "\" is mapped twice");
                }
            }
        }
        Set<String> services = new HashSet<>();
        if (columns != null) {
            columns.forEach(c -> services.add(c.service()));
        }
        for (Edge edge : edges == null ? List.<Edge>of() : edges) {
            for (String service : List.of(edge.from(), edge.to())) {
                if (!services.contains(service)) {
                    problems.add("the call graph names \"" + service + "\", which has no column");
                }
            }
            if (edge.from().equals(edge.to())) {
                problems.add("the call graph has a self-loop on \"" + edge.from() + "\"");
            }
        }
        long before = java.util.Arrays.stream(csv.timeSec()).filter(t -> t < injectTimeSec).count();
        if (before < MIN_NORMAL_ROWS) {
            problems.add("only " + before + " rows come before the injection time; at least "
                    + MIN_NORMAL_ROWS + " are needed to learn what normal looks like");
        }
        if (before == csv.timeSec().length) {
            problems.add("the injection time is after the last row");
        }
        if (!blank(gtService) && !services.contains(gtService)) {
            problems.add("ground-truth service \"" + gtService + "\" has no column");
        }
        if (!blank(gtIndicator) && columns != null
                && columns.stream().noneMatch(c -> c.name().equals(gtIndicator))) {
            problems.add("ground-truth indicator \"" + gtIndicator + "\" is not a mapped column");
        }
        return problems;
    }

    private static boolean blank(String s) {
        return s == null || s.isBlank();
    }
}
