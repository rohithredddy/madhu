package com.xairca.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.jayway.jsonpath.JsonPath;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.hamcrest.Matchers;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/** M9.3 to M9.5 through HTTP: the synthetic lab, uploads, and a benchmark job. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class LabUploadBenchmarkIntegrationTest {

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
    void theLabSavesAGeneratedCaseAndItCanBeAnalysed() throws Exception {
        mvc.perform(post("/api/synthetic").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"nServices\":5,\"faultType\":\"LATENCY\",\"amplification\":0.5,\"noise\":\"MEDIUM\",\"seed\":1}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.caseId").value("synthetic-test"))
                .andExpect(jsonPath("$.source").value("SYNTHETIC"));
        assertThat(DATA.resolve("cases/synthetic-test/meta.json")).exists();
        mvc.perform(post("/api/cases/synthetic-test/analyze").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engine\":\"PARE\",\"delaySeconds\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.evaluation.correctTop1").value(true));
    }

    @Test
    void anUploadBecomesACase() throws Exception {
        String csv = Files.readString(TestData.TINY.resolve("data.csv"));
        String meta = """
                {"caseId":"my-upload","system":"shop","faultType":"latency","injectTimeSec":1700000150,
                 "columns":[{"name":"db_latency","service":"db","metric":"latency"},
                            {"name":"mid_latency","service":"mid","metric":"latency"}],
                 "graphText":"mid -> db","gtService":"db","gtIndicator":"db_latency"}
                """;
        mvc.perform(multipart("/api/uploads")
                        .file(new MockMultipartFile("file", "data.csv", "text/csv", csv.getBytes(StandardCharsets.UTF_8)))
                        .file(new MockMultipartFile("meta", "", "application/json", meta.getBytes(StandardCharsets.UTF_8))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.caseId").value("my-upload"))
                .andExpect(jsonPath("$.source").value("UPLOAD"))
                .andExpect(jsonPath("$.nColumns").value(2));
        mvc.perform(get("/api/cases/my-upload")).andExpect(status().isOk())
                .andExpect(jsonPath("$.meta.faultType").value("LATENCY"))
                .andExpect(jsonPath("$.meta.graph.source").value("USER"));
    }

    @Test
    void aBadUploadListsItsProblems() throws Exception {
        String meta = """
                {"caseId":"bad","injectTimeSec":1700000010,
                 "columns":[{"name":"nope","service":"x","metric":"cpu"}],"graphText":"x -> y"}
                """;
        mvc.perform(multipart("/api/uploads")
                        .file(new MockMultipartFile("file", "data.csv", "text/csv",
                                Files.readAllBytes(TestData.TINY.resolve("data.csv"))))
                        .file(new MockMultipartFile("meta", "", "application/json", meta.getBytes(StandardCharsets.UTF_8))))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.details").value(Matchers.containsString("\"nope\" is not in the CSV")))
                .andExpect(jsonPath("$.details").value(Matchers.containsString("only 10 rows")));
    }

    @Test
    void guessColumns() throws Exception {
        mvc.perform(post("/api/uploads/guess-columns").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"header\":\"time,cart_mem,front-end_latency-90\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[1].service").value("front-end"))
                .andExpect(jsonPath("$[1].metric").value("latency-90"));
    }

    @Test
    void aBenchmarkRunsToTheEndAndSummarises() throws Exception {
        String started = mvc.perform(post("/api/benchmarks").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"system\":\"tiny-test\",\"engines\":[\"PARE\",\"NSIGMA\"],\"delays\":[0,30]}"))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString();
        String jobId = JsonPath.read(started, "$.id");
        String body = "";
        long deadline = System.currentTimeMillis() + 30_000;
        while (System.currentTimeMillis() < deadline) {
            body = mvc.perform(get("/api/benchmarks/" + jobId)).andReturn().getResponse().getContentAsString();
            if (!JsonPath.read(body, "$.status").equals("QUEUED") && !JsonPath.read(body, "$.status").equals("RUNNING")) {
                break;
            }
            Thread.sleep(100);
        }
        assertThat((String) JsonPath.read(body, "$.status")).as(body).isEqualTo("DONE");
        assertThat((Integer) JsonPath.read(body, "$.done")).isEqualTo(4);
        assertThat((Integer) JsonPath.read(body, "$.summary.rows.length()")).isEqualTo(4);
        assertThat(((Number) JsonPath.read(body, "$.summary.rows[0].ac1")).doubleValue()).isEqualTo(1.0);
        mvc.perform(get("/api/benchmarks/" + jobId + "/report").param("format", "csv"))
                .andExpect(status().isOk())
                .andExpect(org.springframework.test.web.servlet.result.MockMvcResultMatchers.content()
                        .string(Matchers.startsWith("run_id,case_id,engine")));
    }
}
