package com.xairca.backend;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import com.xairca.backend.analyze.AnalyzeRequest;
import com.xairca.backend.analyze.AnalyzeResponse;
import com.xairca.backend.analyze.FallbackRanker;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * A stand-in for the Python engine, on a real HTTP port, for integration tests.
 *
 * <p>It parses each request exactly as Python would have to (so a request the real
 * engine could not read fails here too), keeps the raw JSON so a test can search it
 * for leaked ground truth, and answers with the Java NSigma ranking under the name the
 * caller asked for. The JDK's own HTTP server is enough; no extra test dependency.
 */
public final class FakeEngine implements AutoCloseable {

    private final HttpServer server;
    private final ObjectMapper mapper = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, true);
    private final List<String> requests = new CopyOnWriteArrayList<>();

    public FakeEngine() {
        try {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
        server.createContext("/health", ex -> reply(ex, "{\"status\":\"ok\",\"version\":\"fake\"}"));
        server.createContext("/v1/engines", ex -> reply(ex,
                "[{\"name\":\"PARE\",\"description\":\"fake\"},{\"name\":\"NSIGMA\",\"description\":\"fake\"}]"));
        server.createContext("/v1/analyze", this::analyze);
        server.createContext("/v1/synthetic", this::synthetic);
        server.start();
    }

    public String url() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    public List<String> requests() {
        return requests;
    }

    private void analyze(HttpExchange exchange) throws IOException {
        String body = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
        requests.add(body);
        try {
            AnalyzeRequest request = mapper.readValue(body, AnalyzeRequest.class);
            AnalyzeResponse ranked = new FallbackRanker().rank(request);
            AnalyzeResponse answer = new AnalyzeResponse(ranked.requestId(), request.engine(), "fake",
                    ranked.tookMs(), ranked.verdict(), ranked.alarmTimeSec(), null,
                    ranked.windowStartSec(), ranked.windowEndSec(), ranked.services(),
                    ranked.indicators(), ranked.warnings());
            reply(exchange, 200, mapper.writeValueAsString(answer));
        } catch (RuntimeException | IOException e) {
            // Like the real engine: a request it cannot read is a 422 with the reason.
            reply(exchange, 422, mapper.writeValueAsString(
                    java.util.Map.of("error", "invalid request", "details", String.valueOf(e.getMessage()))));
        }
    }

    /**
     * Answers with the tiny test case in the JSON case form of docs/06 section 2,
     * renamed so it does not collide with the copy already in the catalog.
     */
    private void synthetic(HttpExchange exchange) throws IOException {
        exchange.getRequestBody().readAllBytes();
        com.xairca.backend.cases.CaseData tiny = new com.xairca.backend.cases.CaseLoader(mapper)
                .load(TestData.TINY);
        com.xairca.backend.cases.CaseMeta m = tiny.meta();
        java.util.Map<String, Object> meta = new java.util.LinkedHashMap<>();
        meta.put("caseId", "synthetic-test");
        meta.put("source", "SYNTHETIC");
        meta.put("system", m.system());
        meta.put("faultType", m.faultType());
        meta.put("injectTimeSec", m.injectTimeSec());
        meta.put("groundTruth", m.groundTruth());
        meta.put("columns", m.columns());
        meta.put("graph", m.graph());
        meta.put("notes", "from the fake engine");
        java.util.List<java.util.List<Double>> values = new java.util.ArrayList<>();
        for (double[] row : tiny.values()) {
            java.util.List<Double> boxed = new java.util.ArrayList<>();
            for (double v : row) {
                boxed.add(Double.isFinite(v) ? v : null);
            }
            values.add(boxed);
        }
        reply(exchange, mapper.writeValueAsString(java.util.Map.of(
                "meta", meta, "timeSec", tiny.timeSec(), "values", values)));
    }

    private static void reply(HttpExchange exchange, String json) throws IOException {
        reply(exchange, 200, json);
    }

    private static void reply(HttpExchange exchange, int status, String json) throws IOException {
        byte[] bytes = json.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().add("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
