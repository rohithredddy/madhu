package com.xairca.backend.api;

/** The body of every 4xx/5xx response (docs/06 section 4). */
public record ApiError(String error, String details) {}
