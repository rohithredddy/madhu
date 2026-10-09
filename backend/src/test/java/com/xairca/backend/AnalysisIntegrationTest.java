package com.xairca.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Path;
import org.hamcrest.Matchers;
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
 * M8's "done when", end to end through HTTP: with the engine running,
 * POST /api/cases/{id}/analyze returns a full AnalysisRun; with it stopped, the Java
 * fallback answers and says so.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class AnalysisIntegrationTest {

    static final FakeEngine ENGINE = new FakeEngine();
    static final Path DATA = TestData.dataDirWithTiny();

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("app.data-dir", DATA::toString);
        registry.add("app.engine-url", ENGINE::url);
    }

    @AfterAll
    static void stop() {
        ENGINE.close();
    }

    @Autowired
    MockMvc mvc;

    @Test
    void analyzeReturnsAFullRunScoredAgainstGroundTruth() throws Exception {
        mvc.perform(post("/api/cases/tiny/analyze").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engine\":\"PARE\",\"delaySeconds\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.engine").value("PARE"))
                .andExpect(jsonPath("$.mode").value("ONE_CLICK"))
                .andExpect(jsonPath("$.response.services[0].service").value("db"))
                .andExpect(jsonPath("$.explanation.headline").value(Matchers.startsWith("Likely root cause: db")))
                .andExpect(jsonPath("$.groundTruth.service").value("db"))
                .andExpect(jsonPath("$.evaluation.correctTop1").value(true))
                .andExpect(jsonPath("$.evaluation.symptomError").value(false));

        // Hard rule 4, at the real boundary: what crossed the wire holds no answer.
        // The request names every column (it must), but has no field saying which one
        // is the answer.
        assertThat(ENGINE.requests()).isNotEmpty().allSatisfy(body ->
                assertThat(body).doesNotContain("groundTruth").doesNotContain("\"indicator\""));
    }

    @Test
    void theRunIsStoredAndHasAReport() throws Exception {
        String body = mvc.perform(post("/api/cases/tiny/analyze").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engine\":\"NSIGMA\",\"delaySeconds\":30}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String runId = com.jayway.jsonpath.JsonPath.read(body, "$.runId");

        mvc.perform(get("/api/runs/" + runId)).andExpect(status().isOk())
                .andExpect(jsonPath("$.delaySeconds").value(30));
        mvc.perform(get("/api/runs").param("caseId", "tiny")).andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(Matchers.greaterThanOrEqualTo(1)));
        mvc.perform(get("/api/runs/" + runId + "/report").param("format", "md"))
                .andExpect(status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content()
                        .string(Matchers.containsString("# Analysis report: tiny")));
    }

    @Test
    void compareRunsEachEngine() throws Exception {
        mvc.perform(post("/api/cases/tiny/compare").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engines\":[\"PARE\",\"NSIGMA\"],\"delaySeconds\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[1].engine").value("NSIGMA"));
    }

    @Test
    void casesSeriesAndErrors() throws Exception {
        mvc.perform(get("/api/cases")).andExpect(status().isOk())
                .andExpect(jsonPath("$.items[0].caseId").value("tiny"));
        mvc.perform(get("/api/cases/tiny/series").param("columns", "db_latency,mid_cpu")
                        .param("maxPoints", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.series.length()").value(2))
                .andExpect(jsonPath("$.step").value(4));
        mvc.perform(get("/api/cases/nope")).andExpect(status().isNotFound())
                .andExpect(jsonPath("$.error").value("no case 'nope'"));
        mvc.perform(post("/api/cases/tiny/analyze").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engine\":\"PARE\",\"delaySeconds\":-5}"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/health")).andExpect(status().isOk()).andExpect(jsonPath("$.engine").value(true));
    }
}
