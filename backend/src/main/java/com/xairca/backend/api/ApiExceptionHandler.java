package com.xairca.backend.api;

import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.common.EngineException;
import com.xairca.backend.common.NotFoundException;
import java.util.stream.Collectors;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;

/**
 * Turns exceptions into {@code {"error", "details"}} with the right status:
 * 400 for a bad request, 404 for an unknown id, 502 when the engine is needed and
 * unavailable, 500 for anything unexpected (docs/03 section 5).
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);

    @ExceptionHandler(NotFoundException.class)
    public ResponseEntity<ApiError> notFound(NotFoundException e) {
        return status(HttpStatus.NOT_FOUND, e.getMessage(), null);
    }

    @ExceptionHandler(BadRequestException.class)
    public ResponseEntity<ApiError> badRequest(BadRequestException e) {
        String details = e.problems().isEmpty() ? null : String.join("; ", e.problems());
        return status(HttpStatus.BAD_REQUEST, e.getMessage(), details);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiError> invalid(MethodArgumentNotValidException e) {
        String details = e.getBindingResult().getFieldErrors().stream()
                .map(error -> error.getField() + ": " + error.getDefaultMessage())
                .collect(Collectors.joining("; "));
        return status(HttpStatus.BAD_REQUEST, "invalid request", details);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class,
            MissingServletRequestParameterException.class, IllegalArgumentException.class})
    public ResponseEntity<ApiError> unreadable(Exception e) {
        return status(HttpStatus.BAD_REQUEST, "invalid request", e.getMessage());
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ApiError> tooLarge(MaxUploadSizeExceededException e) {
        return status(HttpStatus.PAYLOAD_TOO_LARGE, "the file is too large", e.getMessage());
    }

    @ExceptionHandler(EngineException.class)
    public ResponseEntity<ApiError> engine(EngineException e) {
        return status(HttpStatus.BAD_GATEWAY, "the Python engine is not available", e.getMessage());
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiError> unexpected(Exception e) {
        log.error("unexpected error", e);
        return status(HttpStatus.INTERNAL_SERVER_ERROR, "something went wrong", e.getMessage());
    }

    private static ResponseEntity<ApiError> status(HttpStatus status, String error, String details) {
        return ResponseEntity.status(status).body(new ApiError(error, details));
    }
}
