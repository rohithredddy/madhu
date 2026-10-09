package com.xairca.backend.api;

import com.xairca.backend.analyze.AnalyzerClient;
import com.xairca.backend.analyze.FallbackRanker;
import com.xairca.backend.common.EngineException;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * GET /api/engines: the Python engines plus the Java fallback. When Python is down
 * only the fallback is listed, and {@code available} says so.
 */
@RestController
public class EngineController {

    private final AnalyzerClient client;

    public EngineController(AnalyzerClient client) {
        this.client = client;
    }

    public record EngineInfo(String name, String description, boolean available) {}

    @GetMapping("/api/engines")
    public List<EngineInfo> engines() {
        List<EngineInfo> out = new ArrayList<>();
        try {
            for (Map<String, String> engine : client.engines()) {
                out.add(new EngineInfo(engine.get("name"), engine.get("description"), true));
            }
        } catch (EngineException e) {
            // Python is down: list nothing from it rather than a stale guess.
        }
        out.add(new EngineInfo(FallbackRanker.ENGINE_NAME,
                "Java NSigma, used automatically when the Python engine is not available", true));
        return out;
    }
}
