package com.xairca.backend.analyze;

import com.xairca.backend.cases.CallGraph;
import com.xairca.backend.cases.ColumnInfo;
import java.util.List;
import java.util.Map;

/**
 * The request sent to the Python engine, exactly as docs/06 section 3 defines it.
 *
 * <p>There is deliberately no field for the ground truth: an engine must never be
 * told the answer (hard rule 4). A test checks the serialised JSON.
 *
 * @param params optional engine settings with camelCase names (useChangePoint,
 *     topK, ...); missing keys use the engine's defaults
 */
public record AnalyzeRequest(
        String requestId,
        String engine,
        long alarmTimeSec,
        List<ColumnInfo> columns,
        Window normal,
        Window recent,
        CallGraph graph,
        Map<String, Object> params) {

    /**
     * A block of rows. {@code values[row][column]}; a missing reading is {@code null},
     * never 0 and never the string "NaN".
     */
    public record Window(long[] timeSec, Double[][] values) {

        public int nRows() {
            return timeSec.length;
        }

        /** Convert from the case's arrays, turning NaN into null. */
        public static Window of(long[] timeSec, double[][] rows) {
            Double[][] boxed = new Double[rows.length][];
            for (int r = 0; r < rows.length; r++) {
                boxed[r] = new Double[rows[r].length];
                for (int c = 0; c < rows[r].length; c++) {
                    double value = rows[r][c];
                    boxed[r][c] = Double.isFinite(value) ? value : null;
                }
            }
            return new Window(timeSec, boxed);
        }

        /** Back to primitive arrays, null becoming NaN. */
        public double[][] toPrimitive() {
            double[][] out = new double[values.length][];
            for (int r = 0; r < values.length; r++) {
                out[r] = new double[values[r].length];
                for (int c = 0; c < values[r].length; c++) {
                    Double value = values[r][c];
                    out[r][c] = value == null ? Double.NaN : value;
                }
            }
            return out;
        }
    }
}
