package com.xairca.backend.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.TestData;
import com.xairca.backend.common.NotFoundException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;

class CaseCatalogServiceTest {

    @Test
    void scansTheCasesFolderAndSummarises() {
        Path dir = TestData.dataDirWithTiny();
        CaseCatalogService catalog = new CaseCatalogService(TestData.properties(dir),
                new CaseLoader(new ObjectMapper()));
        catalog.refresh();

        CaseSummary summary = catalog.summary("tiny");
        assertThat(summary.nRows()).isEqualTo(200);
        assertThat(summary.nColumns()).isEqualTo(6);
        assertThat(summary.gtService()).isEqualTo("db");
        assertThat(catalog.list("SYNTHETIC", null, null, null, 0, 10).total()).isEqualTo(1);
        assertThat(catalog.list("RCAEVAL_RE1", null, null, null, 0, 10).total()).isZero();
    }

    @Test
    void replayableOnlyWhenTheInjectionComesAfterTheBaseline() {
        Path dir = TestData.dataDirWithTiny();
        // 150 rows before the injection: fewer than a 300-row baseline, more than 100.
        CaseCatalogService strict = new CaseCatalogService(TestData.properties(dir, 300),
                new CaseLoader(new ObjectMapper()));
        strict.refresh();
        assertThat(strict.summary("tiny").replayable()).isFalse();

        CaseCatalogService loose = new CaseCatalogService(TestData.properties(dir, 100),
                new CaseLoader(new ObjectMapper()));
        loose.refresh();
        assertThat(loose.summary("tiny").replayable()).isTrue();
    }

    @Test
    void aBrokenFolderIsSkippedNotFatal() throws Exception {
        Path dir = TestData.dataDirWithTiny();
        Path broken = Files.createDirectories(dir.resolve("cases").resolve("broken"));
        Files.writeString(broken.resolve("meta.json"), "{ not json");
        Files.writeString(broken.resolve("data.csv"), "time\n1\n");
        CaseCatalogService catalog = new CaseCatalogService(TestData.properties(dir),
                new CaseLoader(new ObjectMapper()));
        catalog.refresh();
        assertThat(catalog.all()).extracting(CaseSummary::caseId).containsExactly("tiny");
    }

    @Test
    void anUnknownCaseIsNotFound() {
        CaseCatalogService catalog = new CaseCatalogService(
                TestData.properties(TestData.dataDirWithTiny()), new CaseLoader(new ObjectMapper()));
        catalog.refresh();
        assertThatThrownBy(() -> catalog.load("nope")).isInstanceOf(NotFoundException.class);
    }
}
