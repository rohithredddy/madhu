package com.xairca.backend.benchmark;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.analyze.AnalysisService;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.common.NotFoundException;
import com.xairca.backend.config.AppProperties;
import com.xairca.backend.runs.AnalysisRun;
import com.xairca.backend.runs.AnalysisRunRepository;
import jakarta.annotation.PreDestroy;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Background benchmark jobs (docs/03 section 4.9): every selected case x engine x
 * delay, analysed through the same {@link AnalysisService} as a one-click run and
 * stored with the job's id, then summarised.
 *
 * <p>Paper numbers come from the Python scripts; this is the interactive view of the
 * same measurement, and M9.5 checks the two agree.
 */
@Service
public class BenchmarkService {

    private static final Logger log = LoggerFactory.getLogger(BenchmarkService.class);
    public static final int MAX_CELLS = 5000;

    private final CaseCatalogService catalog;
    private final AnalysisService analysis;
    private final AnalysisRunRepository runs;
    private final BenchmarkJobRepository jobs;
    private final AccuracyCalculator calculator;
    private final ObjectMapper mapper;
    private final ExecutorService jobRunner = Executors.newSingleThreadExecutor();
    private final ExecutorService workers;

    public BenchmarkService(CaseCatalogService catalog, AnalysisService analysis, AnalysisRunRepository runs,
                            BenchmarkJobRepository jobs, AccuracyCalculator calculator, ObjectMapper mapper,
                            AppProperties properties) {
        this.catalog = catalog;
        this.analysis = analysis;
        this.runs = runs;
        this.jobs = jobs;
        this.calculator = calculator;
        this.mapper = mapper;
        this.workers = Executors.newFixedThreadPool(properties.benchmark().workers());
    }

    /** Which cases, engines and delays. Null filters match everything. */
    public record Request(String source, String system, String faultType, Integer maxCases,
                          List<String> engines, List<Integer> delays) {}

    /** A job as the page shows it. */
    public record JobView(String id, Instant createdAt, String status, int total, int done, int failed,
                          List<String> engines, List<Integer> delays, BenchmarkSummary summary) {}

    public JobView start(Request request) {
        if (request.engines() == null || request.engines().isEmpty()) {
            throw new BadRequestException("choose at least one engine");
        }
        List<Integer> delays = request.delays() == null || request.delays().isEmpty()
                ? List.of(0) : request.delays();
        if (delays.stream().anyMatch(d -> d < 0 || d > AnalysisService.MAX_DELAY_SECONDS)) {
            throw new BadRequestException("delays must be between 0 and " + AnalysisService.MAX_DELAY_SECONDS);
        }
        List<CaseSummary> cases = catalog.list(request.source(), request.system(), request.faultType(), null,
                0, 1000).items();
        if (request.maxCases() != null && request.maxCases() > 0 && cases.size() > request.maxCases()) {
            cases = cases.subList(0, request.maxCases());
        }
        if (cases.isEmpty()) {
            throw new BadRequestException("no case matches the filter");
        }
        int total = cases.size() * request.engines().size() * delays.size();
        if (total > MAX_CELLS) {
            throw new BadRequestException("that is " + total + " analyses; narrow it to at most " + MAX_CELLS);
        }
        BenchmarkJob job = new BenchmarkJob(UUID.randomUUID().toString(), Instant.now(), json(request),
                String.join(",", request.engines()), join(delays), total);
        jobs.save(job);
        List<CaseSummary> chosen = List.copyOf(cases);
        jobRunner.submit(() -> run(job.getId(), chosen, request.engines(), delays));
        return view(job);
    }

    private void run(String jobId, List<CaseSummary> cases, List<String> engines, List<Integer> delays) {
        BenchmarkJob job = jobs.findById(jobId).orElseThrow();
        job.setStatus("RUNNING");
        jobs.save(job);
        AtomicInteger done = new AtomicInteger();
        AtomicInteger failed = new AtomicInteger();
        List<BenchmarkSummary.Failure> failures = Collections.synchronizedList(new ArrayList<>());
        List<java.util.concurrent.Future<?>> futures = new ArrayList<>();
        for (CaseSummary c : cases) {
            for (String engine : engines) {
                for (int delay : delays) {
                    futures.add(workers.submit(() -> {
                        try {
                            analysis.analyzeForBenchmark(c.caseId(), engine, delay, jobId);
                        } catch (RuntimeException e) {
                            failed.incrementAndGet();
                            failures.add(new BenchmarkSummary.Failure(c.caseId(), engine, delay, e.getMessage()));
                        }
                        progress(jobId, done.incrementAndGet(), failed.get());
                    }));
                }
            }
        }
        try {
            for (java.util.concurrent.Future<?> f : futures) {
                f.get();
            }
            BenchmarkJob finished = jobs.findById(jobId).orElseThrow();
            finished.setDone(done.get());
            finished.setFailed(failed.get());
            finished.setSummaryJson(json(summary(jobId, failures)));
            finished.setStatus("DONE");
            jobs.save(finished);
        } catch (Exception e) {
            log.error("benchmark {} failed", jobId, e);
            BenchmarkJob broken = jobs.findById(jobId).orElseThrow();
            broken.setStatus("FAILED");
            jobs.save(broken);
        }
    }

    private synchronized void progress(String jobId, int done, int failed) {
        BenchmarkJob job = jobs.findById(jobId).orElseThrow();
        job.setDone(done);
        job.setFailed(failed);
        jobs.save(job);
    }

    private BenchmarkSummary summary(String jobId, List<BenchmarkSummary.Failure> failures) {
        List<AccuracyCalculator.Result> results = new ArrayList<>();
        for (AnalysisRun run : runs.findByBenchmarkJobId(jobId)) {
            boolean hasIndicator = catalog.exists(run.getCaseId())
                    && catalog.meta(run.getCaseId()).groundTruth() != null
                    && catalog.meta(run.getCaseId()).groundTruth().indicator() != null;
            results.add(new AccuracyCalculator.Result(run.getEngine(), run.getDelaySeconds(),
                    run.getRankGtService(), run.getRankGtIndicator(), hasIndicator, run.getSymptomError(),
                    run.getVerdict(), run.getTookMs()));
        }
        return new BenchmarkSummary(calculator.summarise(results), List.copyOf(failures));
    }

    public JobView get(String jobId) {
        return view(jobs.findById(jobId).orElseThrow(() -> new NotFoundException("no benchmark '" + jobId + "'")));
    }

    public List<JobView> list() {
        return jobs.findTop50ByOrderByCreatedAtDesc().stream().map(this::view).toList();
    }

    /** Every analysed cell of a job, one CSV line each. */
    public String csv(String jobId) {
        get(jobId);
        StringBuilder out = new StringBuilder(
                "run_id,case_id,engine,delay_s,verdict,top1_service,top1_indicator,rank_gt_service,"
                        + "rank_gt_indicator,correct_top1,symptom_error,took_ms\n");
        for (AnalysisRun run : runs.findByBenchmarkJobId(jobId)) {
            out.append(String.join(",", run.getId(), run.getCaseId(), run.getEngine(),
                    String.valueOf(run.getDelaySeconds()), str(run.getVerdict()), str(run.getTop1Service()),
                    str(run.getTop1Indicator()), str(run.getRankGtService()), str(run.getRankGtIndicator()),
                    str(run.getCorrectTop1()), str(run.getSymptomError()), String.valueOf(run.getTookMs())))
                    .append('\n');
        }
        return out.toString();
    }

    /** The summary as a Markdown table. */
    public String markdown(String jobId) {
        JobView job = get(jobId);
        StringBuilder md = new StringBuilder("# Benchmark " + jobId + "\n\n");
        md.append("Status ").append(job.status()).append(", ").append(job.done()).append(" of ")
                .append(job.total()).append(" analyses, ").append(job.failed()).append(" failed.\n\n");
        if (job.summary() != null) {
            md.append("| Engine | Delay s | Cases | AC@1 | AC@3 | Avg@5 | ExpAC@1 | ExpAC@3 | Symptom rate | Mean ms |\n");
            md.append("|---|---|---|---|---|---|---|---|---|---|\n");
            for (BenchmarkSummary.Row r : job.summary().rows()) {
                md.append(String.format(Locale.ROOT, "| %s | %d | %d | %.3f | %.3f | %.3f | %s | %s | %s | %.0f |%n",
                        r.engine(), r.delaySeconds(), r.cases(), r.ac1(), r.ac3(), r.avg5(),
                        fmt(r.expAc1()), fmt(r.expAc3()), fmt(r.symptomRate()), r.meanMs()));
            }
            md.append("\nPaper results are produced by the research scripts; this page reproduces them "
                    + "interactively.\n");
        }
        return md.toString();
    }

    private JobView view(BenchmarkJob job) {
        BenchmarkSummary summary = null;
        if (job.getSummaryJson() != null) {
            try {
                summary = mapper.readValue(job.getSummaryJson(), BenchmarkSummary.class);
            } catch (JsonProcessingException e) {
                throw new IllegalStateException("stored benchmark summary is not valid JSON", e);
            }
        }
        List<Integer> delays = job.getDelays().isEmpty() ? List.of()
                : Arrays.stream(job.getDelays().split(",")).map(Integer::valueOf).toList();
        return new JobView(job.getId(), job.getCreatedAt(), job.getStatus(), job.getTotal(), job.getDone(),
                job.getFailed(), List.of(job.getEngines().split(",")), delays, summary);
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private static String join(List<Integer> values) {
        return String.join(",", values.stream().map(String::valueOf).toList());
    }

    private static String str(Object value) {
        return value == null ? "" : value.toString();
    }

    private static String fmt(Double value) {
        return value == null ? "" : String.format(Locale.ROOT, "%.3f", value);
    }

    @PreDestroy
    public void shutdown() {
        jobRunner.shutdownNow();
        workers.shutdownNow();
    }
}
