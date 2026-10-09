package com.xairca.backend.cases;

import java.util.List;

/**
 * One case fully loaded: every row of data.csv plus its meta.json.
 *
 * <p>Values are row-major, {@code values[row][column]}, in the order of
 * {@link #columns()}; a missing reading is {@code NaN}. Arrays are not copied on the
 * way out, for speed, so callers must not modify them.
 */
public final class CaseData {

    private final CaseMeta meta;
    private final long[] timeSec;
    private final double[][] values;

    public CaseData(CaseMeta meta, long[] timeSec, double[][] values) {
        if (timeSec.length != values.length) {
            throw new IllegalArgumentException(
                    timeSec.length + " times for " + values.length + " rows");
        }
        this.meta = meta;
        this.timeSec = timeSec;
        this.values = values;
    }

    public CaseMeta meta() {
        return meta;
    }

    public List<ColumnInfo> columns() {
        return meta.columns();
    }

    public long[] timeSec() {
        return timeSec;
    }

    public double[][] values() {
        return values;
    }

    public int nRows() {
        return timeSec.length;
    }

    public int nColumns() {
        return meta.columns().size();
    }

    /** Index of a column by name, or -1. */
    public int columnIndex(String name) {
        List<ColumnInfo> columns = meta.columns();
        for (int i = 0; i < columns.size(); i++) {
            if (columns.get(i).name().equals(name)) {
                return i;
            }
        }
        return -1;
    }
}
