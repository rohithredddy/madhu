package com.xairca.backend.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Single-server mode (docs/02 section 4): when the built React app has been copied
 * into {@code static/} ({@code npm run build:backend}), a page address such as
 * {@code /cases/re1-ob-cartservice_mem-1} is the app's own route, not a file. This
 * forwards those to {@code index.html} so a bookmark or a reload works.
 *
 * <p>Only plain GETs for paths without a dot, outside {@code /api}, Swagger and the
 * OpenAPI docs, are forwarded; and only when a built UI is present at all, so in
 * development (Vite on :5173) this does nothing.
 */
@Component
public class SpaForwardingFilter extends OncePerRequestFilter {

    private final boolean uiBuilt = new ClassPathResource("static/index.html").exists();

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String path = request.getRequestURI().substring(request.getContextPath().length());
        if (uiBuilt && isAppRoute(request.getMethod(), path)) {
            request.getRequestDispatcher("/index.html").forward(request, response);
            return;
        }
        chain.doFilter(request, response);
    }

    static boolean isAppRoute(String method, String path) {
        return "GET".equals(method)
                && !path.equals("/")
                && !path.startsWith("/api")
                && !path.startsWith("/swagger-ui")
                && !path.startsWith("/v3/api-docs")
                && !path.startsWith("/h2-console")
                && !path.contains(".");
    }
}
