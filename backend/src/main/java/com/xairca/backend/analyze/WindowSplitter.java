package com.xairca.backend.analyze;

import com.xairca.backend.analyze.AnalyzeRequest.Window;
import com.xairca.backend.cases.CaseData;
import com.xairca.backend.config.AppProperties;
import java.util.Arrays;
import org.springframework.stereotype.Component;

/**
 * Cuts a case into the two windows an engine is given: {@code normal} and
 * {@code recent}. The Java side of the one window table in docs/05 section 3 step 2:
 *
 * <ul>
 *   <li>normal = rows with {@code time < injectTime - normalGapSeconds}</li>
 *   <li>recent = rows with {@code alarm - recentBefore <= time <= alarm + recentAfter}</li>
 * </ul>
 *
 * <p>Two rules this class exists to enforce, both tested:
 * <ul>
 *   <li><b>No ground truth.</b> It returns only times and values; the answer stays in
 *       the case meta and never reaches a request (hard rule 4).</li>
 *   <li><b>No future rows in replay.</b> With {@code playedRows} set, no window
 *       contains a row that has not been played yet - not even the normal one
 *       (hard rule 5).</li>
 * </ul>
 *
 * <p>Stated assumption (docs/03 section 4.2): the normal window ends at the injection
 * time minus a gap. That is the RCAEval protocol, applied identically to every engine;
 * the replay <em>detector</em> never sees the injection time.
 */
@Component
public class WindowSplitter {

    private final AppProperties properties;

    public WindowSplitter(AppProperties properties) {
        this.properties = properties;
    }

    /** The two windows. */
    public record Windows(Window normal, Window recent) {}

    /** One-click analysis: every row of the case is available. */
    public Windows split(CaseData data, long alarmTimeSec) {
        return split(data, alarmTimeSec, data.nRows());
    }

    /**
     * Replay analysis: only the first {@code playedRows} rows exist yet.
     *
     * @param playedRows how many rows of the case have been played; rows at or after
     *     this index are the future and are never used
     */
    public Windows split(CaseData data, long alarmTimeSec, int playedRows) {
        long[] times = data.timeSec();
        double[][] values = data.values();
        int available = Math.max(0, Math.min(playedRows, data.nRows()));

        long normalEnd = data.meta().injectTimeSec() - properties.normalGapSeconds();
        long recentStart = alarmTimeSec - properties.recentBeforeSeconds();
        long recentEnd = alarmTimeSec + properties.recentAfterSeconds();

        int[] normalRows = new int[available];
        int[] recentRows = new int[available];
        int nNormal = 0;
        int nRecent = 0;
        for (int row = 0; row < available; row++) {
            long t = times[row];
            if (t < normalEnd) {
                normalRows[nNormal++] = row;
            }
            if (t >= recentStart && t <= recentEnd) {
                recentRows[nRecent++] = row;
            }
        }
        return new Windows(
                pick(times, values, Arrays.copyOf(normalRows, nNormal)),
                pick(times, values, Arrays.copyOf(recentRows, nRecent)));
    }

    private static Window pick(long[] times, double[][] values, int[] rows) {
        long[] t = new long[rows.length];
        double[][] v = new double[rows.length][];
        for (int i = 0; i < rows.length; i++) {
            t[i] = times[rows[i]];
            v[i] = values[rows[i]];
        }
        return Window.of(t, v);
    }
}
