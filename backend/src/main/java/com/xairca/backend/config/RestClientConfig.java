package com.xairca.backend.config;

import java.time.Duration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

/**
 * The HTTP client used to call the Python engine, with the timeout from config.
 *
 * <p>A request that takes longer than {@code app.engine-timeout-ms} fails, and the
 * analysis then falls back to the Java ranker (docs/02 section 3.1). The plain JDK
 * request factory is enough: one local service, a handful of requests a minute.
 */
@Configuration
public class RestClientConfig {

    @Bean
    public RestClient engineRestClient(RestClient.Builder builder, AppProperties properties) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(2));
        factory.setReadTimeout(Duration.ofMillis(properties.engineTimeoutMs()));
        return builder.baseUrl(properties.engineUrl()).requestFactory(factory).build();
    }
}
