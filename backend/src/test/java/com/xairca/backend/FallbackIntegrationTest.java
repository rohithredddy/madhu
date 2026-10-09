package com.xairca.backend;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.nio.file.Path;
import org.hamcrest.Matchers;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

/** With the Python engine stopped, analysis still answers - and says it used the fallback. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class FallbackIntegrationTest {

    static final Path DATA = TestData.dataDirWithTiny();

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("app.data-dir", DATA::toString);
        // Nothing listens on port 1: every engine call fails at once.
        registry.add("app.engine-url", () -> "http://127.0.0.1:1");
    }

    @Autowired
    MockMvc mvc;

    @Test
    void theFallbackIsUsedAndSaysSo() throws Exception {
        mvc.perform(post("/api/cases/tiny/analyze").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"engine\":\"PARE\",\"delaySeconds\":0}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.engine").value("NSIGMA_JAVA_FALLBACK"))
                .andExpect(jsonPath("$.response.warnings").value(
                        Matchers.hasItem("engine not available, Java fallback used")))
                .andExpect(jsonPath("$.explanation.notes").value(
                        Matchers.hasItem("Engine not available, Java fallback used.")))
                .andExpect(jsonPath("$.response.services[0].service").value("db"));
    }

    @Test
    void healthAndEnginesReportPythonAsDown() throws Exception {
        mvc.perform(get("/api/health")).andExpect(status().isOk())
                .andExpect(jsonPath("$.engine").value(false));
        mvc.perform(get("/api/engines")).andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(1))
                .andExpect(jsonPath("$[0].name").value("NSIGMA_JAVA_FALLBACK"));
    }
}
