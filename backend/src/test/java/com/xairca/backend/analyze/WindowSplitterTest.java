package com.xairca.backend.analyze;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.TestData;
import com.xairca.backend.analyze.WindowSplitter.Windows;
import com.xairca.backend.cases.CaseData;
import com.xairca.backend.cases.CaseLoader;
import com.xairca.backend.cases.CaseMeta;
import com.xairca.backend.cases.GroundTruth;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Map;
import org.junit.jupiter.api.Test;

/** The windows, and the two rules they must never break: no answer, no future. */
class WindowSplitterTest {

    private static final long T0 = 1_700_000_000L;
    private static final long INJECT = T0 + 150;

    private final CaseData tiny = new CaseLoader(new ObjectMapper()).load(TestData.TINY);
    private final WindowSplitter splitter = new WindowSplitter(TestData.properties(Path.of("x")));

    @Test
    void normalEndsAGapBeforeTheInjectionAndRecentSurroundsTheAlarm() {
        Windows w = splitter.split(tiny, INJECT);
        long[] normal = w.normal().timeSec();
        assertThat(normal[normal.length - 1]).isEqualTo(INJECT - 31);
        assertThat(normal).hasSize(120);
        long[] recent = w.recent().timeSec();
        assertThat(recent[0]).isEqualTo(T0);            // alarm - 300 is before the data
        assertThat(recent[recent.length - 1]).isEqualTo(T0 + 199);  // alarm + 120 is after it
    }

    @Test
    void aLateAlarmMovesTheRecentWindowButNotTheNormalOne() {
        Windows onTime = splitter.split(tiny, INJECT);
        Windows late = splitter.split(tiny, INJECT + 30);
        assertThat(late.normal().timeSec()).isEqualTo(onTime.normal().timeSec());
        assertThat(late.recent().timeSec()[late.recent().nRows() - 1]).isEqualTo(T0 + 199);
    }

    @Test
    void replayNeverSeesARowThatHasNotBeenPlayed() {
        int played = 165;
        Windows w = splitter.split(tiny, INJECT + 10, played);
        long lastPlayed = tiny.timeSec()[played - 1];
        assertThat(Arrays.stream(w.recent().timeSec()).max().orElseThrow()).isLessThanOrEqualTo(lastPlayed);
        assertThat(Arrays.stream(w.normal().timeSec()).max().orElseThrow()).isLessThanOrEqualTo(lastPlayed);
    }

    @Test
    void evenAnEarlyFalseAlarmCannotPullUnplayedNormalRows() {
        // An alarm before the injection: the normal window would reach rows that have
        // not been played yet, so it is cut at the played rows too.
        int played = 60;
        Windows w = splitter.split(tiny, T0 + 59, played);
        assertThat(w.normal().nRows()).isEqualTo(60);
        assertThat(w.normal().timeSec()[59]).isEqualTo(T0 + 59);
    }

    @Test
    void theRequestCarriesNoGroundTruth() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = mapper.writeValueAsString(request(tiny));
        assertThat(json).doesNotContain("groundTruth").doesNotContain("indicator\"");

        // Changing the answer must not change a single byte of what the engine is sent.
        CaseMeta m = tiny.meta();
        CaseMeta otherAnswer = new CaseMeta(m.caseId(), m.source(), m.system(), m.faultType(),
                m.injectTimeSec(), new GroundTruth("front", "front_cpu"), m.columns(), m.graph(), m.notes());
        CaseData relabelled = new CaseData(otherAnswer, tiny.timeSec(), tiny.values());
        assertThat(mapper.writeValueAsString(request(relabelled))).isEqualTo(json);
    }

    private AnalyzeRequest request(CaseData data) {
        Windows w = splitter.split(data, INJECT);
        return new AnalyzeRequest("fixed-id", "PARE", INJECT, data.columns(), w.normal(), w.recent(),
                data.meta().graph(), Map.of());
    }
}
