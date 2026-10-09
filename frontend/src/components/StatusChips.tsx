import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Health } from "../api/types";

/** Is the backend up, and can it reach the Python engine? Re-checked every 15 s. */
export function StatusChips() {
  const [health, setHealth] = useState<Health | null>(null);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    let alive = true;
    const check = () =>
      api
        .health()
        .then((h) => {
          if (alive) {
            setHealth(h);
            setBackendDown(false);
          }
        })
        .catch(() => alive && setBackendDown(true));
    check();
    const timer = setInterval(check, 15000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  const backend = backendDown ? "down" : health ? "up" : "";
  const engine = backendDown || !health ? "" : health.engine ? "up" : "down";
  return (
    <>
      <span className={`chip ${backend}`} title="The Java backend on port 8080">
        <span className="dot" /> Backend {backendDown ? "not reachable" : health ? "OK" : "…"}
      </span>
      <span className={`chip ${engine}`} title="The Python engine on port 8000">
        <span className="dot" /> Python engine{" "}
        {backendDown || !health ? "…" : health.engine ? "OK" : "down (Java fallback in use)"}
      </span>
    </>
  );
}
