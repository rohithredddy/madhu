package com.xairca.backend.cases;

import com.fasterxml.jackson.annotation.JsonIgnore;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Who calls whom. Edges run caller -> callee, so a fault in a callee travels up to
 * its callers: the services affected by a fault are its ancestors (decision 1).
 *
 * @param source where the edges came from: TRACES, STATIC_ARCHITECTURE, CORRELATION,
 *     SYNTHETIC_TRUE, USER or NONE (docs/06 section 2)
 */
public record CallGraph(String source, List<Edge> edges) {

    public CallGraph {
        source = source == null ? "NONE" : source;
        edges = edges == null ? List.of() : List.copyOf(edges);
    }

    public static CallGraph empty() {
        return new CallGraph("NONE", List.of());
    }

    /**
     * Not part of the JSON. Without {@code @JsonIgnore}, Jackson reads "isEmpty" as a
     * property and sends {@code "empty": true} to the engine, whose graph model
     * forbids unknown fields - every request would be refused. Found by the
     * integration test's strict fake engine.
     */
    @JsonIgnore
    public boolean isEmpty() {
        return edges.isEmpty();
    }

    /**
     * Every service that calls {@code service}, directly or through others. These are
     * the services that can look broken only because {@code service} is broken, which
     * is what the symptom-error check asks about. Cycles terminate; a service is never
     * its own ancestor.
     */
    public Set<String> ancestors(String service) {
        Set<String> found = new LinkedHashSet<>();
        Deque<String> queue = new ArrayDeque<>();
        queue.add(service);
        while (!queue.isEmpty()) {
            String current = queue.poll();
            for (Edge edge : edges) {
                if (edge.to().equals(current) && !edge.from().equals(service)
                        && found.add(edge.from())) {
                    queue.add(edge.from());
                }
            }
        }
        return found;
    }

    /** Every service named by an edge. */
    public Set<String> services() {
        Set<String> names = new LinkedHashSet<>();
        for (Edge edge : edges) {
            names.add(edge.from());
            names.add(edge.to());
        }
        return names;
    }
}
