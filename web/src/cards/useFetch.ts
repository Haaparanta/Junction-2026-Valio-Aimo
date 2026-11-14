import { useEffect, useState } from "react";

/** Fetch by id; refetch every `pollMs` when given (approval status, PLAN M9.2). */
export function useFetch<T>(id: string | null, load: (id: string) => Promise<T>, pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!id) {
      setData(null);
      return;
    }
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
  }, [id, load, pollMs]);
  return { data, error };
}
