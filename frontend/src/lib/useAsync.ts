import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Load something when the component mounts or a dependency changes, keeping the
 * loading and error states every page needs to show (docs/04 section 5).
 */
export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  // The caller lists what the load depends on, as with useEffect.
  const run = useCallback(load, deps);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    run()
      .then((value) => alive && setData(value))
      .catch((e: unknown) => alive && setError(describe(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [run, tick]);

  return { data, error, loading, reload: () => setTick((t) => t + 1) };
}

/** The backend's own words for an error, with its details when it gave some. */
export function describe(e: unknown): string {
  if (e instanceof ApiError) {
    return e.details ? `${e.message}: ${e.details}` : e.message;
  }
  return e instanceof Error ? e.message : String(e);
}
