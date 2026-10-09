package com.xairca.backend.common;

import java.util.List;

/**
 * The request cannot be served as asked: a bad setting, an invalid upload. Becomes
 * HTTP 400, with every problem listed so the user can fix them in one go.
 */
public class BadRequestException extends RuntimeException {

    private final List<String> problems;

    public BadRequestException(String message) {
        this(message, List.of());
    }

    public BadRequestException(String message, List<String> problems) {
        super(message);
        this.problems = List.copyOf(problems);
    }

    public List<String> problems() {
        return problems;
    }
}
