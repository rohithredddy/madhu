package com.xairca.backend.config;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SpaForwardingFilterTest {

    @Test
    void appRoutesAreForwardedAndEverythingElseIsNot() {
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/cases/re1-ob-cartservice_mem-1")).isTrue();
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/replay")).isTrue();
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/api/cases")).isFalse();
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/assets/index-abc.js")).isFalse();
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/swagger-ui/index.html")).isFalse();
        assertThat(SpaForwardingFilter.isAppRoute("POST", "/cases")).isFalse();
        assertThat(SpaForwardingFilter.isAppRoute("GET", "/")).isFalse();
    }
}
