package com.xairca.backend.replay;

import com.xairca.backend.analyze.AnalysisService;
import com.xairca.backend.cases.CaseCatalogService;
import com.xairca.backend.cases.CaseData;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.common.NotFoundException;
import com.xairca.backend.config.AppProperties;
import jakarta.annotation.PreDestroy;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Plays recorded cases back row by row, as if live (docs/03 section 4.8).
 *
 * <p>Each session advances on a shared scheduler, {@code speed} rows per second,
 * feeding the {@link OnlineDetector}. When the detector has alarmed and a short wait
 * has passed, the analysis runs on a separate thread with only the rows played so far
 * (hard rule 5), so a slow engine never stalls the playback of other sessions.
 */
@Service
public class ReplayService {

    private static final Logger log = LoggerFactory.getLogger(ReplayService.class);
    public static final Set<Integer> SPEEDS = Set.of(1, 5, 20, 50);
    private static final Duration KEEP_FINISHED = Duration.ofMinutes(30);
    private static final int WINDOW_ROWS = 300;

    private final CaseCatalogService catalog;
    private final AnalysisService analysis;
    private final AppProperties properties;
    private final Map<String, ReplaySession> sessions = new ConcurrentHashMap<>();
    private final ScheduledExecutorService ticker = Executors.newScheduledThreadPool(2, named("replay-tick"));
    private final ExecutorService analyser = Executors.newFixedThreadPool(2, named("replay-analyse"));

    public ReplayService(CaseCatalogService catalog, AnalysisService analysis, AppProperties properties) {
        this.catalog = catalog;
        this.analysis = analysis;
        this.properties = properties;
    }

    /** Start playing a case. Returns the new session's id. */
    public String start(String caseId, int speed, String engine) {
        if (!SPEEDS.contains(speed)) {
            throw new BadRequestException("speed must be one of " + SPEEDS);
        }
        CaseData data = catalog.load(caseId);
        AppProperties.Replay settings = properties.replay();
        if (data.nRows() <= settings.baselineRows()) {
            throw new BadRequestException("case " + caseId + " has only " + data.nRows()
                    + " rows; the detector needs " + settings.baselineRows() + " to learn from first");
        }
        cleanUp();
        long running = sessions.values().stream().filter(s -> !s.isOver()).count();
        if (running >= settings.maxSessions()) {
            throw new BadRequestException("at most " + settings.maxSessions()
                    + " replays can run at once; stop one first");
        }
        // The detector is built from the column count and the replay settings only.
        // It is never told when the fault was injected (docs/03 section 4.7).
        OnlineDetector detector = new OnlineDetector(data.nColumns(), settings.baselineRows(),
                settings.alarmConsecutiveRows(), settings.targetFalseAlarmRate(),
                settings.recalibrateEveryRows(), settings.gapRows());
        String chosen = engine == null || engine.isBlank() ? properties.defaultEngine() : engine;
        ReplaySession session = new ReplaySession(UUID.randomUUID().toString(), data, chosen, speed,
                detector, settings.waitAfterAlarmRows());
        sessions.put(session.id(), session);
        long periodMs = Math.max(1, 1000 / speed);
        ScheduledFuture<?> task = ticker.scheduleAtFixedRate(() -> tick(session), 0, periodMs,
                TimeUnit.MILLISECONDS);
        session.setTask(task);
        log.info("replay {} of {} at {} rows/s with {}", session.id(), caseId, speed, chosen);
        return session.id();
    }

    private void tick(ReplaySession session) {
        try {
            if (session.advance()) {
                long alarm = session.alarmTimeSec();
                int played = session.cursor();
                analyser.submit(() -> {
                    try {
                        session.explained(analysis.analyzeReplay(session.caseId(), session.engine(), alarm, played));
                    } catch (RuntimeException e) {
                        log.warn("replay analysis failed: {}", e.getMessage());
                        session.failed(e.getMessage());
                    }
                });
            }
        } catch (RuntimeException e) {
            // A failing tick must not kill the scheduler thread for every session.
            log.error("replay tick failed", e);
            session.failed(e.getMessage());
        }
    }

    public ReplayState state(String sessionId, boolean showGroundTruth) {
        return session(sessionId).state(WINDOW_ROWS, showGroundTruth);
    }

    public void stop(String sessionId) {
        session(sessionId).stop();
    }

    private ReplaySession session(String sessionId) {
        ReplaySession session = sessions.get(sessionId);
        if (session == null) {
            throw new NotFoundException("no replay session '" + sessionId + "'");
        }
        return session;
    }

    /** Forget sessions that ended more than 30 minutes ago. */
    void cleanUp() {
        Instant cutoff = Instant.now().minus(KEEP_FINISHED);
        sessions.values().removeIf(s -> s.isOver() && s.ended() != null && s.ended().isBefore(cutoff));
    }

    @PreDestroy
    public void shutdown() {
        ticker.shutdownNow();
        analyser.shutdownNow();
    }

    private static java.util.concurrent.ThreadFactory named(String prefix) {
        return runnable -> {
            Thread thread = new Thread(runnable, prefix + "-" + UUID.randomUUID().toString().substring(0, 6));
            thread.setDaemon(true);
            return thread;
        };
    }
}
