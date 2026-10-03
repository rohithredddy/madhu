# backend - Java Spring Boot application backend

The hub of the application: the case catalog, replay with the live Java detector, calls to the
Python engine, the Java fallback ranker, plain-language explanations, H2 storage, benchmark jobs
and report export. React talks only to this; it never calls Python.

Built with the Maven Wrapper (`mvnw`), so no system Maven is needed - only a JDK 21.
Spec: `docs/03_JAVA_BACKEND_SPEC.md`.

    cd backend && ./mvnw -q clean verify
    cd backend && ./mvnw spring-boot:run
