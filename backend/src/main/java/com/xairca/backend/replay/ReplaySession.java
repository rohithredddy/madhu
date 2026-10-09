package com.xairca.backend.replay;

import com.xairca.backend.cases.CaseData;
import com.xairca.backend.cases.ColumnInfo;
import com.xairca.backend.runs.AnalysisRunDto;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ScheduledFuture;

/**
 * One case being played back row by row (docs/03 section 4.8).
 *
 * <p>Holds the cursor, the detector, every score so far and the result once
 * explained. The scheduler thread advances it and the web thread reads it, so every
 * method is synchronized.
 */
public final class ReplaySession {

    public enum Phase { LEARNING, WATCHING, ALARM, EXPLAINED, FINISHED, STOPPED }

    private final String id;
    private final CaseData data;
    private final String engine;
    private final int speed;
    private final OnlineDetector detector;
    private final int waitAfterAlarmRows;
    private final double[] scores;
    private final Instant created = Instant.now();

    private int cursor;
    private Phase phase = Phase.LEARNING;
    private Integer alarmRow;
    private boolean analysing;
    private AnalysisRunDto run;
    private String error;
    private Instant ended;
    private ScheduledFuture<?> task;

    public ReplaySession(String id, CaseData data, String engine, int speed, OnlineDetector detector,
                         int waitAfterAlarmRows) {
        this.id = id;
        this.data = data;
        this.engine = engine;
        this.speed = speed;
        this.detector = detector;
        this.waitAfterAlarmRows = waitAfterAlarmRows;
        this.scores = new double[data.nRows()];
    }

    /**
     * Play one more row. Returns true when the analysis should start now: the alarm has
     * fired and {@code waitAfterAlarmRows} more rows have been played since.
     */
    public synchronized boolean advance() {
        if (phase == Phase.EXPLAINED || phase == Phase.FINISHED || phase == Phase.STOPPED || analysing) {
            return false;
        }
        if (cursor >= data.nRows()) {
            finish(Phase.FINISHED);
            return false;
        }
        scores[cursor] = detector.push(data.timeSec()[cursor], data.values()[cursor]);
        cursor++;
        if (detector.state() == OnlineDetector.State.WATCHING) {
            phase = Phase.WATCHING;
        } else if (detector.state() == OnlineDetector.State.ALARM) {
            if (alarmRow == null) {
                alarmRow = cursor;
            }
            phase = Phase.ALARM;
            if (cursor >= alarmRow + waitAfterAlarmRows || cursor >= data.nRows()) {
                analysing = true;
                return true;
            }
        }
        return false;
    }

    public synchronized void explained(AnalysisRunDto result) {
        analysing = false;
        run = result;
        finish(Phase.EXPLAINED);
    }

    public synchronized void failed(String message) {
        analysing = false;
        error = message;
        finish(Phase.FINISHED);
    }

    public synchronized void stop() {
        if (phase != Phase.EXPLAINED && phase != Phase.FINISHED) {
            finish(Phase.STOPPED);
        }
    }

    private void finish(Phase end) {
        phase = end;
        ended = Instant.now();
        if (task != null) {
            task.cancel(false);
        }
    }

    public synchronized void setTask(ScheduledFuture<?> task) {
        this.task = task;
    }

    /** The snapshot the page draws: the last {@code window} rows of everything. */
    public synchronized ReplayState state(int window, boolean showGroundTruth) {
        int from = Math.max(0, cursor - window);
        List<Long> times = new ArrayList<>();
        List<Double> detectorScores = new ArrayList<>();
        for (int r = from; r < cursor; r++) {
            times.add(data.timeSec()[r]);
            double s = scores[r];
            detectorScores.add(Double.isFinite(s) ? s : null);
        }
        List<ReplayState.Series> series = new ArrayList<>();
        for (int c : watched(from, showGroundTruth)) {
            List<Double> values = new ArrayList<>();
            for (int r = from; r < cursor; r++) {
                double v = data.values()[r][c];
                values.add(Double.isFinite(v) ? v : null);
            }
            series.add(new ReplayState.Series(data.columns().get(c).name(), values));
        }
        List<String> top = detector.topColumnsAtAlarm().stream()
                .map(c -> data.columns().get(c).name()).toList();
        return new ReplayState(id, data.meta().caseId(), engine, phase.name(), cursor, data.nRows(), speed,
                detector.threshold(), times, detectorScores, series, detector.alarmTimeSec(), top, run, error);
    }

    /**
     * Up to six columns to draw. With "show ground truth" on, the true service's own
     * columns - a presentation choice only, never an input to the detector. Otherwise
     * the detector's choice: the alarm's top columns, or before an alarm the columns
     * that moved most in the visible window.
     */
    private List<Integer> watched(int from, boolean showGroundTruth) {
        Set<Integer> chosen = new LinkedHashSet<>();
        if (showGroundTruth && data.meta().groundTruth() != null) {
            List<ColumnInfo> columns = data.columns();
            for (int c = 0; c < columns.size(); c++) {
                if (columns.get(c).service().equals(data.meta().groundTruth().service())) {
                    chosen.add(c);
                }
            }
        }
        chosen.addAll(detector.topColumnsAtAlarm());
        if (chosen.size() < 6) {
            List<Integer> byMovement = new ArrayList<>();
            double[] peak = new double[data.nColumns()];
            for (int c = 0; c < data.nColumns(); c++) {
                byMovement.add(c);
                for (int r = from; r < cursor; r++) {
                    double z = detector.z(c, data.values()[r][c]);
                    if (Double.isFinite(z) && z > peak[c]) {
                        peak[c] = z;
                    }
                }
            }
            byMovement.sort(Comparator.comparingDouble((Integer c) -> -peak[c]).thenComparing(c -> c));
            chosen.addAll(byMovement);
        }
        return chosen.stream().limit(6).toList();
    }

    public String id() {
        return id;
    }

    public synchronized Phase phase() {
        return phase;
    }

    public synchronized int cursor() {
        return cursor;
    }

    public String caseId() {
        return data.meta().caseId();
    }

    public String engine() {
        return engine;
    }

    public synchronized Long alarmTimeSec() {
        return detector.alarmTimeSec();
    }

    public Instant created() {
        return created;
    }

    public synchronized Instant ended() {
        return ended;
    }

    public synchronized boolean isOver() {
        return phase == Phase.EXPLAINED || phase == Phase.FINISHED || phase == Phase.STOPPED;
    }
}
