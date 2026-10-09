package com.xairca.backend.cases;

/** One call-graph edge: {@code from} calls {@code to} (caller -> callee). */
public record Edge(String from, String to) {}
