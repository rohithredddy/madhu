package com.xairca.backend.cases;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

/**
 * Writes a case folder in the format of docs/06 section 2 - the same format
 * {@code experiments/case_format.py} writes - so a case made by the synthetic lab or an
 * upload is read back by {@link CaseLoader} like any exported one.
 */
@Component
public class CaseWriter {

    /** Letters, digits, '.', '_' and '-': safe as a folder name on every system. */
    public static final Pattern CASE_ID = Pattern.compile("^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$");

    private final ObjectMapper mapper;

    public CaseWriter(ObjectMapper mapper) {
        this.mapper = mapper.copy().enable(SerializationFeature.INDENT_OUTPUT);
    }

    /**
     * Write {@code meta} and the rows into {@code root/<caseId>/}, replacing any
     * earlier case of the same id. Missing readings (NaN) become empty cells.
     */
    public Path write(Path root, CaseMeta meta, long[] timeSec, double[][] values) {
        if (!CASE_ID.matcher(meta.caseId()).matches()) {
            throw new IllegalArgumentException("case id '" + meta.caseId() + "' is not a safe folder name");
        }
        Path folder = root.resolve(meta.caseId());
        try {
            Files.createDirectories(folder);
            try (BufferedWriter out = Files.newBufferedWriter(folder.resolve("data.csv"), StandardCharsets.UTF_8)) {
                out.write("time");
                for (ColumnInfo column : meta.columns()) {
                    out.write(',');
                    out.write(column.name());
                }
                out.write('\n');
                for (int r = 0; r < timeSec.length; r++) {
                    out.write(Long.toString(timeSec[r]));
                    for (double v : values[r]) {
                        out.write(',');
                        if (Double.isFinite(v)) {
                            out.write(Double.toString(v));
                        }
                    }
                    out.write('\n');
                }
            }
            mapper.writeValue(folder.resolve("meta.json").toFile(), meta);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot write case " + meta.caseId(), e);
        }
        return folder;
    }
}
