package com.xairca.backend.analyze;

import com.fasterxml.jackson.databind.JsonNode;
import com.xairca.backend.common.EngineException;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

/**
 * Calls the Python engine over REST (docs/03 section 4.3). JSON exactly as
 * docs/06 section 3. Every failure - not running, timed out, refused the request -
 * becomes an {@link EngineException}, which the analysis turns into a fallback.
 */
@Component
public class AnalyzerClient {

    private static final Logger log = LoggerFactory.getLogger(AnalyzerClient.class);

    private final RestClient client;

    public AnalyzerClient(RestClient engineRestClient) {
        this.client = engineRestClient;
    }

    /** POST /v1/analyze. */
    public AnalyzeResponse analyze(AnalyzeRequest request) {
        long started = System.nanoTime();
        try {
            AnalyzeResponse response = client.post().uri("/v1/analyze")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(request)
                    .retrieve()
                    .body(AnalyzeResponse.class);
            log.info("engine {} rows={}+{} columns={} took {} ms", request.engine(),
                    request.normal().nRows(), request.recent().nRows(), request.columns().size(),
                    (System.nanoTime() - started) / 1_000_000);
            if (response == null) {
                throw new EngineException("the engine returned an empty answer");
            }
            return response;
        } catch (RestClientResponseException e) {
            throw new EngineException("the engine refused the request (HTTP "
                    + e.getStatusCode().value() + "): " + e.getResponseBodyAsString(), e);
        } catch (RestClientException e) {
            throw new EngineException("the engine is not reachable: " + e.getMessage(), e);
        }
    }

    /** GET /v1/engines: name and description of every engine. */
    public List<Map<String, String>> engines() {
        try {
            List<Map<String, String>> engines = client.get().uri("/v1/engines").retrieve()
                    .body(new ParameterizedTypeReference<>() {});
            return engines == null ? List.of() : engines;
        } catch (RestClientException e) {
            throw new EngineException("the engine is not reachable: " + e.getMessage(), e);
        }
    }

    /** POST /v1/synthetic: one generated case in the JSON case format. */
    public JsonNode synthetic(Map<String, Object> settings) {
        try {
            return client.post().uri("/v1/synthetic").contentType(MediaType.APPLICATION_JSON)
                    .body(settings).retrieve().body(JsonNode.class);
        } catch (RestClientResponseException e) {
            throw new EngineException("the engine refused the settings (HTTP "
                    + e.getStatusCode().value() + "): " + e.getResponseBodyAsString(), e);
        } catch (RestClientException e) {
            throw new EngineException("the engine is not reachable: " + e.getMessage(), e);
        }
    }

    /** GET /health: is the engine up? Never throws. */
    public boolean isUp() {
        try {
            JsonNode health = client.get().uri("/health").retrieve().body(JsonNode.class);
            return health != null && "ok".equals(health.path("status").asText());
        } catch (RestClientException e) {
            return false;
        }
    }
}
