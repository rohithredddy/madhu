# frontend - React user interface

The interface used to present the whole project: browse recorded failures, analyze one, compare
engines, watch a replay as if it were live, run the synthetic lab, and view benchmark accuracy.

React 18 + Vite + TypeScript. Talks only to the Java backend on port 8080 (Vite proxies `/api`).
Spec: `docs/04_REACT_FRONTEND_SPEC.md`.

    cd frontend && npm install && npm run dev
    cd frontend && npm run build
