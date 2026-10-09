package com.xairca.backend;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * The xai-rca backend: the hub between the React frontend and the Python engine.
 *
 * <p>React calls only this application; this application calls Python over REST and
 * stores everything (H2). See docs/02_ARCHITECTURE.md.
 */
@SpringBootApplication
@ConfigurationPropertiesScan
public class XaiRcaApplication {

    public static void main(String[] args) {
        SpringApplication.run(XaiRcaApplication.class, args);
    }
}
