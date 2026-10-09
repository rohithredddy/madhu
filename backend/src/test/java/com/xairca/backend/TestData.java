package com.xairca.backend;

import com.xairca.backend.config.AppProperties;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;

/** Shared helpers for tests: properties, the tiny case, and the Python sample files. */
public final class TestData {

    /** The committed cross-language fixtures (docs/03 section 4.4). */
    public static final Path SAMPLES = Path.of("..", "analyzer", "samples");

    /** src/test/resources/cases/tiny: 200 rows, 3 services, a db latency fault at row 150. */
    public static final Path TINY = Path.of("src", "test", "resources", "cases", "tiny");

    private TestData() {}

    public static AppProperties properties(Path dataDir) {
        return properties(dataDir, 300);
    }

    public static AppProperties properties(Path dataDir, int baselineRows) {
        return new AppProperties(dataDir.toString(), dataDir.resolve("cases").toString(),
                dataDir.resolve("uploads").toString(), "http://localhost:1", 2000, "PARE", 30, 300,
                120, new AppProperties.Replay(3, baselineRows, 3, 20, 0.01),
                new AppProperties.Benchmark(2));
    }

    /** A temporary data folder holding a copy of the tiny case. */
    public static Path dataDirWithTiny() {
        try {
            Path dir = Files.createTempDirectory("xairca-test");
            copy(TINY, dir.resolve("cases").resolve("tiny"));
            Files.createDirectories(dir.resolve("uploads"));
            return dir;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }

    public static void copy(Path from, Path to) {
        try (Stream<Path> files = Files.walk(from)) {
            for (Path source : files.toList()) {
                Path target = to.resolve(from.relativize(source).toString());
                if (Files.isDirectory(source)) {
                    Files.createDirectories(target);
                } else {
                    Files.createDirectories(target.getParent());
                    Files.copy(source, target);
                }
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
