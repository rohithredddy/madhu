package com.xairca.backend.explain;

import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Plain-language names for metrics, used in explanation sentences (docs/03 section 4.6).
 *
 * <p>cpu -> "CPU usage", mem -> "memory use", latency -> "response time", and so on.
 * Percentile latencies from the benchmark ({@code latency-90}) read as
 * "response time (90th percentile)". Anything unknown is shown as its own name rather
 * than guessed at.
 */
public final class MetricLabels {

    private static final Map<String, String> LABELS = Map.of(
            "cpu", "CPU usage",
            "mem", "memory use",
            "latency", "response time",
            "error", "error rate",
            "rps", "request rate",
            "disk", "disk activity",
            "net", "network traffic");

    private static final Pattern PERCENTILE = Pattern.compile("latency-(\\d+)");

    private MetricLabels() {}

    public static String label(String metric) {
        if (metric == null) {
            return "an unknown metric";
        }
        String known = LABELS.get(metric);
        if (known != null) {
            return known;
        }
        Matcher m = PERCENTILE.matcher(metric);
        if (m.matches()) {
            return "response time (" + m.group(1) + "th percentile)";
        }
        return metric;
    }
}
