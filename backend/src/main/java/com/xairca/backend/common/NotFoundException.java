package com.xairca.backend.common;

/** Something asked for by id does not exist. Becomes HTTP 404. */
public class NotFoundException extends RuntimeException {

    public NotFoundException(String message) {
        super(message);
    }
}
