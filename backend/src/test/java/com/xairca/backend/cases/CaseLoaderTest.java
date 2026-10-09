package com.xairca.backend.cases;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.TestData;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class CaseLoaderTest {

    private final CaseLoader loader = new CaseLoader(new ObjectMapper());

    @Test
    void loadsTheTinyCase() {
        CaseData data = loader.load(TestData.TINY);
        assertThat(data.nRows()).isEqualTo(200);
        assertThat(data.nColumns()).isEqualTo(6);
        assertThat(data.meta().groundTruth().service()).isEqualTo("db");
        assertThat(data.meta().graph().edges()).hasSize(2);
        assertThat(data.timeSec()[0]).isEqualTo(1_700_000_000L);
    }

    @Test
    void anEmptyCellIsMissingNotZero() {
        CaseData data = loader.load(TestData.TINY);
        int midCpu = data.columnIndex("mid_cpu");
        assertThat(data.values()[40][midCpu]).isNaN();
        assertThat(data.values()[41][midCpu]).isGreaterThan(10);
    }

    @Test
    void countsRowsBeforeAGivenTime() {
        CaseLoader.RowCount count = loader.countRows(TestData.TINY, 1_700_000_150L);
        assertThat(count.total()).isEqualTo(200);
        assertThat(count.before()).isEqualTo(150);
    }

    @Test
    void refusesAHeaderThatDoesNotMatchTheMeta(@TempDir Path dir) throws Exception {
        TestData.copy(TestData.TINY, dir);
        Path csv = dir.resolve("data.csv");
        String text = Files.readString(csv).replaceFirst("front_cpu", "front_mem");
        Files.writeString(csv, text);
        assertThatThrownBy(() -> loader.load(dir)).hasMessageContaining("meta.json says 'front_cpu'");
    }

    @Test
    void ancestorsAreTheCallersOfACallee() {
        CallGraph graph = loader.readMeta(TestData.TINY).graph();
        assertThat(graph.ancestors("db")).containsExactlyInAnyOrder("mid", "front");
        assertThat(graph.ancestors("front")).isEmpty();
    }
}
