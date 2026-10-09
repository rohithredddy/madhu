package com.xairca.backend.upload;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.StringReader;
import java.io.UncheckedIOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * An uploaded CSV, read once into columns by name.
 *
 * @param timeSec the "time" column, or null when there is none
 * @param rows values in header order, without the time column; empty cell = NaN
 */
public record ParsedCsv(List<String> header, long[] timeSec, List<double[]> rows, List<String> problems) {

    /** Parse, collecting format problems rather than stopping at the first. */
    public static ParsedCsv parse(String text) {
        List<String> problems = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new StringReader(text))) {
            String headerLine = reader.readLine();
            if (headerLine == null || headerLine.isBlank()) {
                return new ParsedCsv(List.of(), null, List.of(), List.of("the CSV is empty"));
            }
            List<String> header = Arrays.stream(headerLine.split(",", -1)).map(String::trim).toList();
            int timeIndex = header.indexOf("time");
            List<Long> times = new ArrayList<>();
            List<double[]> rows = new ArrayList<>();
            String line;
            int lineNumber = 1;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                if (line.isBlank()) {
                    continue;
                }
                String[] cells = line.split(",", -1);
                if (cells.length != header.size()) {
                    problems.add("line " + lineNumber + " has " + cells.length + " cells, the header has "
                            + header.size());
                    if (problems.size() > 10) {
                        break;
                    }
                    continue;
                }
                double[] row = new double[header.size()];
                for (int c = 0; c < header.size(); c++) {
                    String cell = cells[c].trim();
                    try {
                        row[c] = cell.isEmpty() ? Double.NaN : Double.parseDouble(cell);
                    } catch (NumberFormatException e) {
                        problems.add("line " + lineNumber + ", column " + header.get(c) + ": '" + cell
                                + "' is not a number");
                        row[c] = Double.NaN;
                    }
                }
                if (timeIndex >= 0) {
                    times.add((long) row[timeIndex]);
                }
                rows.add(row);
            }
            long[] timeSec = timeIndex < 0 ? null : times.stream().mapToLong(Long::longValue).toArray();
            return new ParsedCsv(header, timeSec, rows, problems);
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    /** The values of the named columns, in the given order, row by row. */
    public double[][] select(List<String> names) {
        int[] index = names.stream().mapToInt(header::indexOf).toArray();
        double[][] out = new double[rows.size()][names.size()];
        for (int r = 0; r < rows.size(); r++) {
            for (int c = 0; c < index.length; c++) {
                out[r][c] = rows.get(r)[index[c]];
            }
        }
        return out;
    }
}
