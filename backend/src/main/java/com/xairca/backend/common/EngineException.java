package com.xairca.backend.common;

/**
 * The Python engine could not be reached or refused a request. Analysis catches it
 * and falls back to the Java ranker; anything that cannot fall back (generating a
 * synthetic case) lets it become HTTP 502.
 */
public class EngineException extends RuntimeException {

    public EngineException(String message, Throwable cause) {
        super(message, cause);
    }

    public EngineException(String message) {
        super(message);
    }
}
