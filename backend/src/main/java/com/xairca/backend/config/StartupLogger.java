package com.xairca.backend.config;

import java.io.IOException;
import java.nio.file.Files;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * Logs, on one line, which data folder this run is using, and makes sure its
 * sub-folders exist.
 *
 * <p>Why it matters (decision 12): a relative path resolved from the wrong working
 * directory would silently create a second, empty database somewhere else. Printing
 * the absolute path at startup makes that impossible to miss.
 */
@Component
public class StartupLogger {

    private static final Logger log = LoggerFactory.getLogger(StartupLogger.class);

    private final AppProperties properties;

    public StartupLogger(AppProperties properties) {
        this.properties = properties;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void logDataDir() throws IOException {
        Files.createDirectories(properties.casesPath());
        Files.createDirectories(properties.uploadsPath());
        log.info("data dir: {} (cases: {}, uploads: {}, engine: {})",
                properties.dataPath(), properties.casesPath(), properties.uploadsPath(),
                properties.engineUrl());
    }
}
