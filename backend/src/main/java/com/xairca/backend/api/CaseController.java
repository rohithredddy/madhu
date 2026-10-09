package com.xairca.backend.api;

import com.xairca.backend.analyze.AnalysisService;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseData;
import com.xairca.backend.cases.CaseMeta;
import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.runs.AnalysisRunDto;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotEmpty;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** The case catalog, its time series, and one-click analysis (docs/03 section 5). */
@RestController
@RequestMapping("/api/cases")
public class CaseController {

    private final CaseCatalogService catalog;
    private final AnalysisService analysis;

    public CaseController(CaseCatalogService catalog, AnalysisService analysis) {
        this.catalog = catalog;
        this.analysis = analysis;
    }

    @GetMapping
    public CaseCatalogService.Page list(
            @RequestParam(required = false) String source,
            @RequestParam(required = false) String system,
            @RequestParam(required = false) String faultType,
            @RequestParam(required = false) String search,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "50") int size) {
        return catalog.list(source, system, faultType, search, page, size);
    }

    /** Meta (with call graph and ground truth) plus the summary, without the data. */
    public record CaseDetail(CaseSummary summary, CaseMeta meta, long firstTimeSec, long lastTimeSec) {}

    @GetMapping("/{caseId}")
    public CaseDetail get(@PathVariable String caseId) {
        CaseData data = catalog.load(caseId);
        long[] t = data.timeSec();
        return new CaseDetail(catalog.summary(caseId), data.meta(),
                t.length == 0 ? 0 : t[0], t.length == 0 ? 0 : t[t.length - 1]);
    }

    /** Values for charts. {@code values[i]} lines up with {@code timeSec[i]}; missing is null. */
    public record Series(String column, List<Double> values) {}

    public record SeriesResponse(List<Long> timeSec, List<Series> series, int step) {}

    /**
     * Time series for charts. Down-sampled by keeping every {@code step}-th row when
     * the range holds more than {@code maxPoints} rows; {@code step} says by how much,
     * so the chart can say so too.
     */
    @GetMapping("/{caseId}/series")
    public SeriesResponse series(@PathVariable String caseId,
                                 @RequestParam String columns,
                                 @RequestParam(required = false) Long from,
                                 @RequestParam(required = false) Long to,
                                 @RequestParam(defaultValue = "1000") int maxPoints) {
        CaseData data = catalog.load(caseId);
        List<String> names = Arrays.stream(columns.split(",")).map(String::trim)
                .filter(s -> !s.isEmpty()).toList();
        int[] indexes = new int[names.size()];
        for (int i = 0; i < names.size(); i++) {
            indexes[i] = data.columnIndex(names.get(i));
            if (indexes[i] < 0) {
                throw new BadRequestException("case " + caseId + " has no column '" + names.get(i) + "'");
            }
        }
        long[] t = data.timeSec();
        List<Integer> rows = new ArrayList<>();
        for (int r = 0; r < t.length; r++) {
            if ((from == null || t[r] >= from) && (to == null || t[r] <= to)) {
                rows.add(r);
            }
        }
        int step = Math.max(1, (int) Math.ceil(rows.size() / (double) Math.max(10, maxPoints)));
        List<Long> times = new ArrayList<>();
        List<List<Double>> columnsOut = new ArrayList<>();
        for (int i = 0; i < names.size(); i++) {
            columnsOut.add(new ArrayList<>());
        }
        for (int k = 0; k < rows.size(); k += step) {
            int r = rows.get(k);
            times.add(t[r]);
            for (int i = 0; i < names.size(); i++) {
                double v = data.values()[r][indexes[i]];
                columnsOut.get(i).add(Double.isFinite(v) ? v : null);
            }
        }
        List<Series> series = new ArrayList<>();
        for (int i = 0; i < names.size(); i++) {
            series.add(new Series(names.get(i), columnsOut.get(i)));
        }
        return new SeriesResponse(times, series, step);
    }

    public record AnalyzeBody(String engine, @Min(0) @Max(600) int delaySeconds) {}

    @PostMapping("/{caseId}/analyze")
    public AnalysisRunDto analyze(@PathVariable String caseId, @Valid @RequestBody AnalyzeBody body) {
        return analysis.analyze(caseId, body.engine(), body.delaySeconds());
    }

    public record CompareBody(@NotEmpty List<String> engines, @Min(0) @Max(600) int delaySeconds) {}

    @PostMapping("/{caseId}/compare")
    public List<AnalysisRunDto> compare(@PathVariable String caseId, @Valid @RequestBody CompareBody body) {
        return analysis.compare(caseId, body.engines(), body.delaySeconds());
    }
}
