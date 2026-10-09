package com.xairca.backend.cases;

/**
 * The known answer of a case. Used only to score a result after an engine has
 * answered; it is never put into a request to an engine (hard rule 4).
 *
 * @param indicator the one correct metric column, or null when the fault type has
 *     no single right metric (RCAEval DISK, DELAY, LOSS)
 */
public record GroundTruth(String service, String indicator) {}
