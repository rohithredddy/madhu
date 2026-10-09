package com.xairca.backend.cases;

/**
 * One metric column: its name in data.csv, the service it belongs to and what it
 * measures. Meaning always comes from this explicit map, never from splitting the
 * column name (docs/06 section 1).
 */
public record ColumnInfo(String name, String service, String metric) {}
