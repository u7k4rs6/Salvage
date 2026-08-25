import { useCallback, useEffect, useRef, useState } from "react";
import { get } from "./api";

export interface ApiState<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/**
 * Server state for one GET. Refetch is explicit: pages call reload() when an SSE event they care
 * about arrives, which is cheaper and more predictable than polling a local SQLite file.
 *
 * `loading` stays false on a refetch that already has data, so a live page does not flash a
 * skeleton every time an event lands.
 */
export function useApi<T>(path: string | null, deps: unknown[] = []): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(path !== null);
  const [nonce, setNonce] = useState(0);
  const hasData = useRef(false);

  useEffect(() => {
    if (path === null) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    if (!hasData.current) setLoading(true);
    get<T>(path, controller.signal)
      .then((body) => {
        setData(body);
        setError(null);
        hasData.current = true;
      })
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setError(cause);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, nonce, ...deps]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);
  return { data, error, loading, reload };
}
