/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to the Java backend, so the browser only ever talks
// to one origin and no CORS setup is needed (docs/02 section 4). React never calls
// the Python engine.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8080",
      "/swagger-ui": "http://localhost:8080",
      "/v3/api-docs": "http://localhost:8080",
    },
  },
  build: {
    // One local app served from disk: a single 800 kB bundle loads instantly, so
    // splitting it would add complexity for nothing.
    chunkSizeWarningLimit: 1200,
  },
  test: {
    environment: "jsdom",
  },
});
