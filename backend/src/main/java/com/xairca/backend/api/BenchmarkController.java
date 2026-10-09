package com.xairca.backend.api;

import com.xairca.backend.benchmark.BenchmarkService;
import com.xairca.backend.common.BadRequestException;
import java.util.List;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Benchmark jobs: start, poll, download (docs/03 section 5). */
@RestController
@RequestMapping("/api/benchmarks")
public class BenchmarkController {

    private final BenchmarkService benchmarks;

    public BenchmarkController(BenchmarkService benchmarks) {
        this.benchmarks = benchmarks;
    }

    @PostMapping
    public BenchmarkService.JobView start(@RequestBody BenchmarkService.Request request) {
        return benchmarks.start(request);
    }

    @GetMapping
    public List<BenchmarkService.JobView> list() {
        return benchmarks.list();
    }

    @GetMapping("/{jobId}")
    public BenchmarkService.JobView get(@PathVariable String jobId) {
        return benchmarks.get(jobId);
    }

    @GetMapping("/{jobId}/report")
    public ResponseEntity<String> report(@PathVariable String jobId,
                                         @RequestParam(defaultValue = "csv") String format) {
        return switch (format) {
            case "csv" -> ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"benchmark-" + jobId + ".csv\"")
                    .contentType(new MediaType("text", "csv")).body(benchmarks.csv(jobId));
            case "md" -> ResponseEntity.ok()
                    .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"benchmark-" + jobId + ".md\"")
                    .contentType(new MediaType("text", "markdown")).body(benchmarks.markdown(jobId));
            default -> throw new BadRequestException("format must be csv or md");
        };
    }
}
