package com.xairca.backend.cases;

import com.xairca.backend.common.NotFoundException;
import com.xairca.backend.config.AppProperties;
import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * The list of every case the application knows, and the one place that loads them.
 *
 * <p>At startup it scans {@code cases-dir} and {@code uploads-dir}; every sub-folder
 * holding meta.json + data.csv is a case. Summaries stay in memory. Full data is
 * read on demand and the last 20 cases are kept in a small LRU cache, because a
 * replay or a benchmark reads the same case many times (docs/03 section 4.1).
 */
@Service
public class CaseCatalogService {

    private static final Logger log = LoggerFactory.getLogger(CaseCatalogService.class);
    private static final int CACHE_SIZE = 20;

    private final AppProperties properties;
    private final CaseLoader loader;
    private final Map<String, Path> folders = new ConcurrentHashMap<>();
    private final Map<String, CaseSummary> summaries = new ConcurrentHashMap<>();
    private final Map<String, CaseData> cache = new LinkedHashMap<>(16, 0.75f, true) {
        @Override
        protected boolean removeEldestEntry(Map.Entry<String, CaseData> eldest) {
            return size() > CACHE_SIZE;
        }
    };

    public CaseCatalogService(AppProperties properties, CaseLoader loader) {
        this.properties = properties;
        this.loader = loader;
    }

    @PostConstruct
    public void refresh() {
        folders.clear();
        summaries.clear();
        synchronized (cache) {
            cache.clear();
        }
        int found = scan(properties.casesPath()) + scan(properties.uploadsPath());
        log.info("case catalog: {} cases", found);
    }

    private int scan(Path root) {
        if (!Files.isDirectory(root)) {
            return 0;
        }
        int count = 0;
        try (Stream<Path> children = Files.list(root)) {
            for (Path folder : children.sorted().toList()) {
                if (Files.isRegularFile(folder.resolve("meta.json"))
                        && Files.isRegularFile(folder.resolve("data.csv"))) {
                    try {
                        register(folder);
                        count++;
                    } catch (RuntimeException e) {
                        // One broken folder must not hide every other case.
                        log.warn("skipping case folder {}: {}", folder, e.getMessage());
                    }
                }
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot list " + root, e);
        }
        return count;
    }

    /** Add (or replace) one case folder in the catalog and return its summary. */
    public CaseSummary register(Path folder) {
        CaseMeta meta = loader.readMeta(folder);
        CaseLoader.RowCount rows = loader.countRows(folder, meta.injectTimeSec());
        CaseSummary summary = new CaseSummary(
                meta.caseId(),
                meta.source(),
                meta.system(),
                meta.faultType(),
                meta.groundTruth() == null ? null : meta.groundTruth().service(),
                rows.total(),
                meta.columns().size(),
                rows.before() >= properties.replay().baselineRows());
        folders.put(meta.caseId(), folder);
        summaries.put(meta.caseId(), summary);
        synchronized (cache) {
            cache.remove(meta.caseId());
        }
        return summary;
    }

    /** Filtered, sorted, paged case list. Null or blank filters match everything. */
    public Page list(String source, String system, String faultType, String search,
                     int page, int size) {
        List<CaseSummary> matching = new ArrayList<>();
        for (CaseSummary summary : summaries.values()) {
            if (matches(source, summary.source()) && matches(system, summary.system())
                    && matches(faultType, summary.faultType())
                    && (search == null || search.isBlank()
                        || summary.caseId().toLowerCase().contains(search.toLowerCase()))) {
                matching.add(summary);
            }
        }
        matching.sort(Comparator.comparing(CaseSummary::caseId));
        int safeSize = Math.max(1, Math.min(size, 1000));
        int from = Math.min(Math.max(page, 0) * safeSize, matching.size());
        int to = Math.min(from + safeSize, matching.size());
        return new Page(matching.subList(from, to), matching.size(), page, safeSize);
    }

    /** A page of the case list. */
    public record Page(List<CaseSummary> items, int total, int page, int size) {}

    public CaseSummary summary(String caseId) {
        CaseSummary summary = summaries.get(caseId);
        if (summary == null) {
            throw new NotFoundException("no case '" + caseId + "'");
        }
        return summary;
    }

    public CaseMeta meta(String caseId) {
        return load(caseId).meta();
    }

    /** The full case, from the cache when possible. */
    public CaseData load(String caseId) {
        Path folder = folders.get(caseId);
        if (folder == null) {
            throw new NotFoundException("no case '" + caseId + "'");
        }
        synchronized (cache) {
            CaseData cached = cache.get(caseId);
            if (cached != null) {
                return cached;
            }
        }
        CaseData data = loader.load(folder);
        synchronized (cache) {
            cache.put(caseId, data);
        }
        return data;
    }

    public List<CaseSummary> all() {
        return summaries.values().stream().sorted(Comparator.comparing(CaseSummary::caseId)).toList();
    }

    public boolean exists(String caseId) {
        return folders.containsKey(caseId);
    }

    private static boolean matches(String wanted, String actual) {
        return wanted == null || wanted.isBlank() || wanted.equalsIgnoreCase(actual);
    }
}
