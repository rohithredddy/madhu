package com.xairca.backend.upload;

import static org.assertj.core.api.Assertions.assertThat;

import com.xairca.backend.cases.ColumnInfo;
import com.xairca.backend.cases.Edge;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.Test;

class UploadValidatorTest {

    private final UploadValidator validator = new UploadValidator();

    private static String csv(int rows) {
        StringBuilder s = new StringBuilder("time,a_cpu,b_latency\n");
        for (int r = 0; r < rows; r++) {
            s.append(1000 + r).append(',').append(r % 7).append(',').append(r % 5).append('\n');
        }
        return s.toString();
    }

    private static final List<ColumnInfo> COLUMNS = List.of(
            new ColumnInfo("a_cpu", "a", "cpu"), new ColumnInfo("b_latency", "b", "latency"));

    @Test
    void aGoodUploadHasNoProblems() {
        assertThat(validator.validate(ParsedCsv.parse(csv(100)), COLUMNS, List.of(new Edge("b", "a")),
                1070, "a", "a_cpu")).isEmpty();
    }

    @Test
    void everyProblemIsReportedAtOnce() {
        List<ColumnInfo> columns = List.of(new ColumnInfo("a_cpu", "a", "cpu"),
                new ColumnInfo("c_mem", "c", "mem"));
        List<String> problems = validator.validate(ParsedCsv.parse(csv(100)), columns,
                List.of(new Edge("b", "a")), 1030, "z", null);
        assertThat(problems).anyMatch(p -> p.contains("\"c_mem\" is not in the CSV"));
        assertThat(problems).anyMatch(p -> p.contains("names \"b\", which has no column"));
        assertThat(problems).anyMatch(p -> p.contains("only 30 rows come before"));
        assertThat(problems).anyMatch(p -> p.contains("ground-truth service \"z\""));
    }

    @Test
    void timeMustExistAndIncrease() {
        assertThat(validator.validate(ParsedCsv.parse("t,a_cpu\n1,2\n"), COLUMNS, List.of(), 0, null, null))
                .containsExactly("the CSV needs a column called \"time\" (epoch seconds)");
        String backwards = "time,a_cpu,b_latency\n" + "5,1,1\n".repeat(1) + "4,1,1\n";
        assertThat(validator.validate(ParsedCsv.parse(backwards), COLUMNS, List.of(), 5, null, null))
                .anyMatch(p -> p.contains("time must increase"));
    }

    @Test
    void graphLinesAreParsedAndBadOnesNamed() {
        List<String> problems = new ArrayList<>();
        List<Edge> edges = UploadService.parseGraph("# comment\nfront -> cart\n\ncart->db\nnonsense", problems);
        assertThat(edges).containsExactly(new Edge("front", "cart"), new Edge("cart", "db"));
        assertThat(problems).singleElement().asString().contains("line 5");
    }

    @Test
    void columnGuessSplitsAtTheLastUnderscore() {
        UploadService service = new UploadService(validator, null, null, null);
        assertThat(service.guessColumns("time,front-end_latency-90,cartservice_mem,weird"))
                .containsExactly(new ColumnInfo("front-end_latency-90", "front-end", "latency-90"),
                        new ColumnInfo("cartservice_mem", "cartservice", "mem"),
                        new ColumnInfo("weird", "weird", "value"));
    }
}
