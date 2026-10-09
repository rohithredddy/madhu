package com.xairca.backend.api;

import com.xairca.backend.analyze.AnalyzerClient;
import com.xairca.backend.cases.CaseCatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** GET /api/health: is the backend up, and can it reach the Python engine? */
@RestController
public class HealthController {

    private final AnalyzerClient client;
    private final CaseCatalogService catalog;

    public HealthController(AnalyzerClient client, CaseCatalogService catalog) {
        this.client = client;
        this.catalog = catalog;
    }

    /** {@code engine} is false when Python is down; analysis then uses the Java fallback. */
    public record Health(String status, boolean engine, int cases) {}

    @GetMapping("/api/health")
    public Health health() {
        return new Health("ok", client.isUp(), catalog.all().size());
    }
}
