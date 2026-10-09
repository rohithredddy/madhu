package com.xairca.backend.replay;

import com.xairca.backend.runs.AnalysisRunDto;
import java.util.List;

/**
 * What the replay page polls every second (docs/06 section 4).
 *
 * @param state LEARNING, WATCHING, ALARM, EXPLAINED, FINISHED or STOPPED
 * @param timeSec the times of the last N played rows
 * @param detectorScore the detector's score for each of those rows; null while learning
 * @param series the last N values of up to six columns worth watching
 * @param error why the analysis after the alarm failed, or null
 */
public record ReplayState(
        String sessionId,
        String caseId,
        String engine,
        String state,
        int cursor,
        int totalRows,
        int speed,
        Double threshold,
        List<Long> timeSec,
        List<Double> detectorScore,
        List<Series> series,
        Long alarmTimeSec,
        List<String> topColumnsAtAlarm,
        AnalysisRunDto run,
        String error) {

    /** One watched column. */
    public record Series(String column, List<Double> values) {}
}
