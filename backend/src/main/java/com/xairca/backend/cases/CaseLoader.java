package com.xairca.backend.cases;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import org.springframework.stereotype.Component;

/**
 * Reads one case folder (data.csv + meta.json, docs/06 section 2) from disk.
 *
 * <p>Plain {@link BufferedReader} on purpose: the format is simple (a header, then
 * numbers, empty cell = missing), and a CSV library would add a dependency for no
 * gain. The header must name exactly the meta.json columns in the same order, after
 * {@code time}; anything else is refused, because a misaligned column would be
 * scored silently under the wrong name.
 */
@Component
public class CaseLoader {

    private final ObjectMapper mapper;

    public CaseLoader(ObjectMapper mapper) {
        this.mapper = mapper.copy().configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    }

    /** Read meta.json. */
    public CaseMeta readMeta(Path folder) {
        try {
            return mapper.readValue(folder.resolve("meta.json").toFile(), CaseMeta.class);
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read " + folder.resolve("meta.json"), e);
        }
    }

    /** Read the whole case. */
    public CaseData load(Path folder) {
        CaseMeta meta = readMeta(folder);
        Path csv = folder.resolve("data.csv");
        List<Long> times = new ArrayList<>();
        List<double[]> rows = new ArrayList<>();
        int width = meta.columns().size();
        try (BufferedReader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            checkHeader(reader.readLine(), meta, csv);
            String line;
            int lineNumber = 1;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (line.isBlank()) {
                    continue;
                }
                String[] cells = line.split(",", -1);
                if (cells.length != width + 1) {
                    throw new IllegalStateException(csv + " line " + lineNumber + " has "
                            + cells.length + " cells, expected " + (width + 1));
                }
                times.add(parseTime(cells[0], csv, lineNumber));
                double[] row = new double[width];
                for (int c = 0; c < width; c++) {
                    row[c] = parseValue(cells[c + 1]);
                }
                rows.add(row);
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read " + csv, e);
        }
        long[] timeSec = times.stream().mapToLong(Long::longValue).toArray();
        return new CaseData(meta, timeSec, rows.toArray(new double[0][]));
    }

    /**
     * Count the rows, and how many of them fall before {@code beforeTimeSec}, without
     * parsing the values. Used by the catalog at startup to fill in the summary.
     */
    public RowCount countRows(Path folder, long beforeTimeSec) {
        Path csv = folder.resolve("data.csv");
        int total = 0;
        int before = 0;
        try (BufferedReader reader = Files.newBufferedReader(csv, StandardCharsets.UTF_8)) {
            reader.readLine();
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) {
                    continue;
                }
                total++;
                int comma = line.indexOf(',');
                String first = comma < 0 ? line : line.substring(0, comma);
                if ((long) Double.parseDouble(first) < beforeTimeSec) {
                    before++;
                }
            }
        } catch (IOException e) {
            throw new UncheckedIOException("cannot read " + csv, e);
        }
        return new RowCount(total, before);
    }

    /** Rows in a case, and how many come before a given time. */
    public record RowCount(int total, int before) {}

    private static void checkHeader(String header, CaseMeta meta, Path csv) {
        if (header == null) {
            throw new IllegalStateException(csv + " is empty");
        }
        String[] names = header.split(",", -1);
        if (!names[0].trim().equals("time")) {
            throw new IllegalStateException(csv + " must start with a \"time\" column");
        }
        List<ColumnInfo> columns = meta.columns();
        if (names.length - 1 != columns.size()) {
            throw new IllegalStateException(csv + " has " + (names.length - 1)
                    + " metric columns but meta.json lists " + columns.size());
        }
        for (int i = 0; i < columns.size(); i++) {
            if (!names[i + 1].trim().equals(columns.get(i).name())) {
                throw new IllegalStateException(csv + " column " + (i + 1) + " is '"
                        + names[i + 1] + "' but meta.json says '" + columns.get(i).name() + "'");
            }
        }
    }

    private static long parseTime(String cell, Path csv, int lineNumber) {
        try {
            return (long) Double.parseDouble(cell.trim());
        } catch (NumberFormatException e) {
            throw new IllegalStateException(csv + " line " + lineNumber + " has no valid time", e);
        }
    }

    /** An empty cell is a missing reading, NaN; never 0. */
    static double parseValue(String cell) {
        String text = cell.trim();
        if (text.isEmpty() || text.equalsIgnoreCase("nan") || text.equalsIgnoreCase("null")) {
            return Double.NaN;
        }
        return Double.parseDouble(text);
    }
}
