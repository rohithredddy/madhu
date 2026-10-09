package com.xairca.backend.synthetic;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.analyze.AnalyzerClient;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseMeta;
import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.cases.CaseWriter;
import com.xairca.backend.common.EngineException;
import com.xairca.backend.config.AppProperties;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * The synthetic lab (docs/03 section 4.10): asks Python for a generated case with a
 * known root cause, saves it as a case folder, and registers it in the catalog.
 *
 * <p>The settings are passed through unchanged in the UPPERCASE form of docs/06
 * section 3; Python validates them and its 422 message comes back to the user.
 */
@Service
public class SyntheticService {

    private final AnalyzerClient client;
    private final CaseWriter writer;
    private final CaseCatalogService catalog;
    private final AppProperties properties;
    private final ObjectMapper mapper;

    public SyntheticService(AnalyzerClient client, CaseWriter writer, CaseCatalogService catalog,
                            AppProperties properties, ObjectMapper mapper) {
        this.client = client;
        this.writer = writer;
        this.catalog = catalog;
        this.properties = properties;
        this.mapper = mapper;
    }

    /** The lab's settings, as the frontend sends them. */
    public record Settings(Integer nServices, String faultType, String rootService, Double propagation,
                           Double amplification, String noise, Integer nNormal, Integer nAbnormal,
                           Integer seed) {}

    public CaseSummary generate(Settings settings) {
        Map<String, Object> body = new LinkedHashMap<>();
        put(body, "nServices", settings.nServices());
        put(body, "faultType", settings.faultType());
        put(body, "rootService", settings.rootService());
        put(body, "propagation", settings.propagation());
        put(body, "amplification", settings.amplification());
        put(body, "noise", settings.noise());
        put(body, "nNormal", settings.nNormal() == null ? 600 : settings.nNormal());
        put(body, "nAbnormal", settings.nAbnormal() == null ? 180 : settings.nAbnormal());
        put(body, "seed", settings.seed());

        JsonNode generated = client.synthetic(body);
        CaseMeta meta;
        try {
            meta = mapper.treeToValue(generated.get("meta"), CaseMeta.class);
        } catch (JsonProcessingException | IllegalArgumentException e) {
            throw new EngineException("the engine returned a synthetic case this backend cannot read", e);
        }
        JsonNode times = generated.get("timeSec");
        JsonNode rows = generated.get("values");
        long[] timeSec = new long[times.size()];
        double[][] values = new double[rows.size()][];
        for (int r = 0; r < timeSec.length; r++) {
            timeSec[r] = times.get(r).asLong();
            JsonNode row = rows.get(r);
            values[r] = new double[row.size()];
            for (int c = 0; c < row.size(); c++) {
                values[r][c] = row.get(c).isNull() ? Double.NaN : row.get(c).asDouble();
            }
        }
        Path folder = writer.write(properties.casesPath(), meta, timeSec, values);
        return catalog.register(folder);
    }

    private static void put(Map<String, Object> body, String key, Object value) {
        if (value != null) {
            body.put(key, value);
        }
    }
}
