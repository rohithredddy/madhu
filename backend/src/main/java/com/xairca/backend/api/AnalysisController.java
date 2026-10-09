package com.xairca.backend.api;

import com.xairca.backend.analyze.AnalysisService;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.report.ReportService;
import com.xairca.backend.runs.AnalysisRunDto;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Past analyses and their reports (docs/03 section 5). */
@RestController
@RequestMapping("/api/runs")
public class AnalysisController {

    private final AnalysisService analysis;
    private final ReportService reports;

    public AnalysisController(AnalysisService analysis, ReportService reports) {
        this.analysis = analysis;
        this.reports = reports;
    }

    @GetMapping
    public List<AnalysisRunDto> list(@RequestParam(required = false) String caseId) {
        return analysis.list(caseId);
    }

    @GetMapping("/{runId}")
    public AnalysisRunDto get(@PathVariable String runId) {
        return analysis.get(runId);
    }

    /** The run as Markdown (to read or download) or JSON. */
    @GetMapping("/{runId}/report")
    public ResponseEntity<?> report(@PathVariable String runId,
                                    @RequestParam(defaultValue = "md") String format) {
        AnalysisRunDto run = analysis.get(runId);
        return switch (format) {
            case "md" -> ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_DISPOSITION,
                            "attachment; filename=\"report-" + run.caseId() + "-" + run.engine() + ".md\"")
                    .contentType(new MediaType("text", "markdown"))
                    .body(reports.runMarkdown(run));
            case "json" -> ResponseEntity.ok().contentType(MediaType.APPLICATION_JSON).body(run);
            default -> throw new BadRequestException("format must be md or json");
        };
    }
}
