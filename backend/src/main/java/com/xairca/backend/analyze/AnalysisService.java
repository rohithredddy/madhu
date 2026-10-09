package com.xairca.backend.analyze;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.analyze.WindowSplitter.Windows;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseData;
import com.xairca.backend.cases.CaseMeta;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.common.EngineException;
import com.xairca.backend.common.NotFoundException;
import com.xairca.backend.config.AppProperties;
import com.xairca.backend.explain.Explanation;
import com.xairca.backend.explain.ExplanationRenderer;
import com.xairca.backend.runs.AnalysisRun;
import com.xairca.backend.runs.AnalysisRunDto;
import com.xairca.backend.runs.AnalysisRunDto.Evaluation;
import com.xairca.backend.runs.AnalysisRunRepository;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Runs one analysis end to end (docs/03 section 4.5):
 * load the case, cut the windows, call the engine (or fall back), render the
 * explanation, score against ground truth, store the run.
 *
 * <p>The order is the point. The engine request is built from the windows and the
 * column map only; the ground truth is read afterwards, by {@link Evaluator}, and
 * cannot influence the answer (hard rule 4).
 */
@Service
public class AnalysisService {

    private static final Logger log = LoggerFactory.getLogger(AnalysisService.class);
    public static final String FALLBACK_NOTE = "engine not available, Java fallback used";
    public static final int MAX_DELAY_SECONDS = 600;

    private final CaseCatalogService catalog;
    private final WindowSplitter splitter;
    private final AnalyzerClient client;
    private final FallbackRanker fallback;
    private final ExplanationRenderer renderer;
    private final AnalysisRunRepository runs;
    private final ObjectMapper mapper;
    private final AppProperties properties;

    public AnalysisService(CaseCatalogService catalog, WindowSplitter splitter, AnalyzerClient client,
                           FallbackRanker fallback, ExplanationRenderer renderer,
                           AnalysisRunRepository runs, ObjectMapper mapper, AppProperties properties) {
        this.catalog = catalog;
        this.splitter = splitter;
        this.client = client;
        this.fallback = fallback;
        this.renderer = renderer;
        this.runs = runs;
        this.mapper = mapper;
        this.properties = properties;
    }

    /** One-click analysis: the alarm is the injection time plus a simulated delay. */
    public AnalysisRunDto analyze(String caseId, String engine, int delaySeconds) {
        return run(caseId, engine, delaySeconds, "ONE_CLICK", null, null, null);
    }

    /** Several engines on the same case and delay, for the compare view. */
    public List<AnalysisRunDto> compare(String caseId, List<String> engines, int delaySeconds) {
        if (engines == null || engines.isEmpty()) {
            throw new BadRequestException("name at least one engine to compare");
        }
        List<AnalysisRunDto> out = new ArrayList<>();
        for (String engine : engines) {
            out.add(analyze(caseId, engine, delaySeconds));
        }
        return out;
    }

    /**
     * Replay analysis: the alarm came from the live detector, and only the rows played
     * so far exist (hard rule 5).
     */
    public AnalysisRunDto analyzeReplay(String caseId, String engine, long alarmTimeSec, int playedRows) {
        return run(caseId, engine, 0, "REPLAY", alarmTimeSec, playedRows, null);
    }

    /** One cell of a benchmark job. */
    public AnalysisRunDto analyzeForBenchmark(String caseId, String engine, int delaySeconds, String jobId) {
        return run(caseId, engine, delaySeconds, "BENCHMARK", null, null, jobId);
    }

    private AnalysisRunDto run(String caseId, String engine, int delaySeconds, String mode,
                               Long replayAlarm, Integer playedRows, String jobId) {
        if (delaySeconds < 0 || delaySeconds > MAX_DELAY_SECONDS) {
            throw new BadRequestException("delaySeconds must be between 0 and " + MAX_DELAY_SECONDS);
        }
        String chosen = engine == null || engine.isBlank() ? properties.defaultEngine() : engine;
        CaseData data = catalog.load(caseId);
        CaseMeta meta = data.meta();

        long alarm = replayAlarm != null ? replayAlarm : meta.injectTimeSec() + delaySeconds;
        Windows windows = playedRows != null
                ? splitter.split(data, alarm, playedRows)
                : splitter.split(data, alarm);
        if (windows.normal().nRows() == 0) {
            throw new BadRequestException("this case has no normal rows before the injection");
        }
        if (windows.recent().nRows() == 0) {
            throw new BadRequestException("there are no rows around the alarm time");
        }
        AnalyzeRequest request = new AnalyzeRequest(UUID.randomUUID().toString(), chosen, alarm,
                meta.columns(), windows.normal(), windows.recent(), meta.graph(), Map.of());

        long started = System.nanoTime();
        AnalyzeResponse response = callEngine(request);
        long tookMs = (System.nanoTime() - started) / 1_000_000;

        Explanation explanation = renderer.render(response);
        Evaluation evaluation = Evaluator.evaluate(response, meta.groundTruth(), meta.graph());

        AnalysisRun entity = new AnalysisRun(UUID.randomUUID().toString(), Instant.now(), caseId,
                response.engine(), mode, delaySeconds);
        entity.setAlarmTimeSec(alarm);
        entity.setChangePointSec(response.changePointSec());
        entity.setVerdict(response.verdict());
        if (!response.services().isEmpty()) {
            entity.setTop1Service(response.services().get(0).service());
            entity.setTop1Indicator(response.services().get(0).topIndicator());
        }
        entity.setConfidence(explanation.confidence());
        if (evaluation != null) {
            entity.setRankGtService(evaluation.rankGtService());
            entity.setRankGtIndicator(evaluation.rankGtIndicator());
            entity.setCorrectTop1(evaluation.correctTop1());
            entity.setCorrectTop3(evaluation.correctTop3());
            entity.setSymptomError(evaluation.symptomError());
        }
        entity.setTookMs(tookMs);
        entity.setBenchmarkJobId(jobId);
        entity.setResponseJson(json(response));
        entity.setExplanationJson(json(explanation));
        entity.setWarnings(json(response.warnings()));
        runs.save(entity);
        return toDto(entity, meta);
    }

    /**
     * The engine, or the Java ranker when the engine cannot answer. A request for the
     * fallback by name goes straight to it.
     */
    private AnalyzeResponse callEngine(AnalyzeRequest request) {
        if (FallbackRanker.ENGINE_NAME.equals(request.engine())) {
            return fallback.rank(request);
        }
        try {
            return client.analyze(request);
        } catch (EngineException e) {
            log.warn("engine call failed ({}); using the Java fallback", e.getMessage());
            return fallback.rank(request).withWarnings(List.of(FALLBACK_NOTE));
        }
    }

    public AnalysisRunDto get(String runId) {
        AnalysisRun run = runs.findById(runId)
                .orElseThrow(() -> new NotFoundException("no run '" + runId + "'"));
        return toDto(run, catalog.exists(run.getCaseId()) ? catalog.meta(run.getCaseId()) : null);
    }

    public List<AnalysisRunDto> list(String caseId) {
        List<AnalysisRun> found = caseId == null || caseId.isBlank()
                ? runs.findTop100ByOrderByCreatedAtDesc()
                : runs.findByCaseIdOrderByCreatedAtDesc(caseId);
        List<AnalysisRunDto> out = new ArrayList<>();
        for (AnalysisRun run : found) {
            out.add(toDto(run, catalog.exists(run.getCaseId()) ? catalog.meta(run.getCaseId()) : null));
        }
        return out;
    }

    /** Rebuild the DTO from the stored entity. */
    public AnalysisRunDto toDto(AnalysisRun run, CaseMeta meta) {
        AnalyzeResponse response = read(run.getResponseJson(), new TypeReference<>() {});
        Explanation explanation = read(run.getExplanationJson(), new TypeReference<>() {});
        Evaluation evaluation = run.getCorrectTop1() == null ? null : new Evaluation(
                run.getRankGtService(), run.getRankGtIndicator(), run.getCorrectTop1(),
                Boolean.TRUE.equals(run.getCorrectTop3()), run.getSymptomError());
        return new AnalysisRunDto(run.getId(), run.getCaseId(), run.getEngine(), run.getMode(),
                run.getDelaySeconds(), run.getCreatedAt(), run.getTookMs(), response, explanation,
                meta == null ? null : meta.groundTruth(), evaluation);
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("cannot store a run as JSON", e);
        }
    }

    private <T> T read(String json, TypeReference<T> type) {
        try {
            return json == null ? null : mapper.readValue(json, type);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("a stored run is not valid JSON", e);
        }
    }
}
