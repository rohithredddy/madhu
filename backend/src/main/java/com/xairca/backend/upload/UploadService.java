package com.xairca.backend.upload;

import com.xairca.backend.cases.CallGraph;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseMeta;
import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.cases.CaseWriter;
import com.xairca.backend.cases.ColumnInfo;
import com.xairca.backend.cases.Edge;
import com.xairca.backend.cases.GroundTruth;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.config.AppProperties;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.springframework.stereotype.Service;

/**
 * Turns a user's CSV, column map and call graph into a case (docs/03 section 4.11).
 *
 * <p>The column map is explicit and checked by the user; {@link #guessColumns} only
 * proposes one by splitting each header at its last underscore. The algorithm never
 * guesses meaning from names (docs/06 section 1) - that happens here, once, in front
 * of a person who can correct it.
 */
@Service
public class UploadService {

    private static final Pattern EDGE = Pattern.compile("^\\s*([^\\s>-][^>]*?)\\s*->\\s*(\\S.*?)\\s*$");

    private final UploadValidator validator;
    private final CaseWriter writer;
    private final CaseCatalogService catalog;
    private final AppProperties properties;

    public UploadService(UploadValidator validator, CaseWriter writer, CaseCatalogService catalog,
                         AppProperties properties) {
        this.validator = validator;
        this.writer = writer;
        this.catalog = catalog;
        this.properties = properties;
    }

    /** What the user filled in beside the CSV. */
    public record UploadMeta(String caseId, String system, String faultType, Long injectTimeSec,
                             List<ColumnInfo> columns, String graphText, String gtService,
                             String gtIndicator) {}

    public CaseSummary upload(String csvText, UploadMeta meta) {
        if (meta.injectTimeSec() == null) {
            throw new BadRequestException("give the injection time (epoch seconds)");
        }
        String caseId = meta.caseId() == null || meta.caseId().isBlank()
                ? "upload-" + System.currentTimeMillis() : meta.caseId().trim();
        if (!CaseWriter.CASE_ID.matcher(caseId).matches()) {
            throw new BadRequestException("the case id may only use letters, digits, '.', '_' and '-'");
        }
        if (catalog.exists(caseId)) {
            throw new BadRequestException("a case called '" + caseId + "' already exists");
        }
        ParsedCsv csv = ParsedCsv.parse(csvText);
        List<String> problems = new ArrayList<>(csv.problems());
        List<Edge> edges = parseGraph(meta.graphText(), problems);
        problems.addAll(validator.validate(csv, meta.columns(), edges, meta.injectTimeSec(),
                meta.gtService(), meta.gtIndicator()));
        if (!problems.isEmpty()) {
            throw new BadRequestException("the upload has problems", problems);
        }

        List<String> names = meta.columns().stream().map(ColumnInfo::name).toList();
        GroundTruth truth = meta.gtService() == null || meta.gtService().isBlank() ? null
                : new GroundTruth(meta.gtService(),
                        meta.gtIndicator() == null || meta.gtIndicator().isBlank() ? null : meta.gtIndicator());
        CaseMeta caseMeta = new CaseMeta(caseId, "UPLOAD",
                meta.system() == null || meta.system().isBlank() ? "uploaded" : meta.system(),
                meta.faultType() == null || meta.faultType().isBlank()
                        ? "UNKNOWN" : meta.faultType().toUpperCase(Locale.ROOT),
                meta.injectTimeSec(), truth, meta.columns(),
                new CallGraph(edges.isEmpty() ? "NONE" : "USER", edges), "uploaded by a user");
        Path folder = writer.write(properties.uploadsPath(), caseMeta, csv.timeSec(), csv.select(names));
        return catalog.register(folder);
    }

    /** A proposed column map: each header split at its last underscore. */
    public List<ColumnInfo> guessColumns(String headerLine) {
        List<ColumnInfo> out = new ArrayList<>();
        for (String raw : headerLine.split(",")) {
            String name = raw.trim();
            if (name.isEmpty() || name.equals("time")) {
                continue;
            }
            int cut = name.lastIndexOf('_');
            out.add(cut > 0 && cut < name.length() - 1
                    ? new ColumnInfo(name, name.substring(0, cut), name.substring(cut + 1))
                    : new ColumnInfo(name, name, "value"));
        }
        return out;
    }

    /** Lines of the form {@code a -> b}; blank lines and lines starting with # are skipped. */
    static List<Edge> parseGraph(String text, List<String> problems) {
        List<Edge> edges = new ArrayList<>();
        if (text == null) {
            return edges;
        }
        int number = 0;
        for (String line : text.split("\\R")) {
            number++;
            if (line.isBlank() || line.trim().startsWith("#")) {
                continue;
            }
            Matcher m = EDGE.matcher(line);
            if (m.matches()) {
                Edge edge = new Edge(m.group(1).trim(), m.group(2).trim());
                if (!edges.contains(edge)) {
                    edges.add(edge);
                }
            } else {
                problems.add("call graph line " + number + " should look like \"caller -> callee\": '" + line.trim() + "'");
            }
        }
        return edges;
    }
}
