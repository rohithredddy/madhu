package com.xairca.backend.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.nio.file.Path;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * Every setting under {@code app.} in application.yml (docs/03 section 3).
 *
 * <p>The window settings are the Java side of the one window table in
 * docs/05 section 3 step 2; if one changes, both sides change together.
 */
@Validated
@ConfigurationProperties(prefix = "app")
public record AppProperties(
        @NotBlank String dataDir,
        @NotBlank String casesDir,
        @NotBlank String uploadsDir,
        @NotBlank String engineUrl,
        @Min(100) int engineTimeoutMs,
        @NotBlank String defaultEngine,
        @Min(0) int normalGapSeconds,
        @Min(1) int recentBeforeSeconds,
        @Min(0) int recentAfterSeconds,
        @Valid @NotNull Replay replay,
        @Valid @NotNull Benchmark benchmark) {

    /** Settings of the replay mode and its live detector (docs/03 section 4.7). */
    public record Replay(
            @Min(1) int maxSessions,
            @Min(20) int baselineRows,
            @Min(1) int alarmConsecutiveRows,
            @Min(0) int waitAfterAlarmRows,
            @DecimalMin("0.0001") @DecimalMax("0.5") double targetFalseAlarmRate) {}

    /** Settings of the background benchmark jobs (docs/03 section 4.9). */
    public record Benchmark(@Min(1) int workers) {}

    /** The data folder as an absolute, normalised path. */
    public Path dataPath() {
        return Path.of(dataDir).toAbsolutePath().normalize();
    }

    public Path casesPath() {
        return Path.of(casesDir).toAbsolutePath().normalize();
    }

    public Path uploadsPath() {
        return Path.of(uploadsDir).toAbsolutePath().normalize();
    }
}
