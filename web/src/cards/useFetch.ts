import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Fetch by id; refetch every `pollMs` when given (approval status, PLAN M9.2), or on `reload()`.
 * A new id starts empty, so a card never shows the previous id's data under the new one.
 */
export function useFetch<T>(id: string | null, load: (id: string) => Promise<T>, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const lastId = useRef<string | null>(null);
  useEffect(() => {
    if (lastId.current !== id) {
      lastId.current = id;
      setData(null);
      setError(null);
    }
    if (!id) return;
    let alive = true;
    const run = () =>
      load(id).then(
        (d) => alive && (setData(d), setError(null)),
        (e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)),
      );
    void run();
    const t = pollMs ? setInterval(run, pollMs) : undefined;
    return () => {
      alive = false;
      if (t) clearInterval(t);
    };
  }, [id, load, pollMs, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, reload };
}
