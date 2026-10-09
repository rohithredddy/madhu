package com.xairca.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.jayway.jsonpath.JsonPath;
import java.nio.file.Path;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/**
 * M9.2: replay a short case at high speed and reach EXPLAINED. The tiny case has 150
 * rows before its fault, so the detector learns from the first 100.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class ReplayIntegrationTest {

    static final FakeEngine ENGINE = new FakeEngine();
    static final Path DATA = TestData.dataDirWithTiny();

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("app.data-dir", DATA::toString);
        registry.add("app.engine-url", ENGINE::url);
        registry.add("app.replay.baseline-rows", () -> "100");
    }

    @AfterAll
    static void stop() {
        ENGINE.close();
    }

    @Autowired
    MockMvc mvc;

    @Test
    void aReplayLearnsWatchesAlarmsAndIsExplained() throws Exception {
        String started = mvc.perform(post("/api/replay").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"caseId\":\"tiny\",\"speed\":50,\"engine\":\"PARE\"}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String sessionId = JsonPath.read(started, "$.sessionId");

        String state = "";
        String body = "";
        long deadline = System.currentTimeMillis() + 30_000;
        while (System.currentTimeMillis() < deadline) {
            body = mvc.perform(get("/api/replay/" + sessionId)).andReturn().getResponse().getContentAsString();
            state = JsonPath.read(body, "$.state");
            if (state.equals("EXPLAINED") || state.equals("FINISHED")) {
                break;
            }
            Thread.sleep(100);
        }
        assertThat(state).as(body).isEqualTo("EXPLAINED");

        long alarm = ((Number) JsonPath.read(body, "$.alarmTimeSec")).longValue();
        int cursor = JsonPath.read(body, "$.cursor");
        // The alarm comes after the fault (row 150), from the data alone.
        assertThat(alarm).isGreaterThanOrEqualTo(1_700_000_150L);
        // No peeking at the future: the analysis used only the rows played by then.
        double windowEnd = ((Number) JsonPath.read(body, "$.run.response.windowEndSec")).doubleValue();
        assertThat(windowEnd).isLessThanOrEqualTo(1_700_000_000L + cursor - 1);
        assertThat((String) JsonPath.read(body, "$.run.mode")).isEqualTo("REPLAY");
        assertThat((String) JsonPath.read(body, "$.run.response.services[0].service")).isEqualTo("db");
    }

    @Test
    void anUnsupportedSpeedIsRefused() throws Exception {
        mvc.perform(post("/api/replay").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"caseId\":\"tiny\",\"speed\":7}"))
                .andExpect(status().isBadRequest());
    }
}
