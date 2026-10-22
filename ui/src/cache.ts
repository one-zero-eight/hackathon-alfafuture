import { useCallback, useRef, useState } from "react";

export interface Entry<T> { status: "loading" | "ok" | "error"; data?: T }

// Lazy per-id cache: load() fetches once per id, drop() forgets it (used when a patch changes it)
export function useCache<T>(fetcher: (id: string) => Promise<T>) {
  const [entries, setEntries] = useState<Record<string, Entry<T>>>({});
  const seen = useRef(new Set<string>());
  const load = useCallback((id: string, force = false) => {
    if (!force && seen.current.has(id)) return;
    seen.current.add(id);
    setEntries(p => ({ ...p, [id]: { status: "loading", data: p[id]?.data } }));
    fetcher(id)
      .then(data => setEntries(p => ({ ...p, [id]: { status: "ok", data } })))
      .catch(() => { seen.current.delete(id); setEntries(p => ({ ...p, [id]: { status: "error" } })); });
  }, [fetcher]);
  const drop = useCallback((id: string) => {
    seen.current.delete(id);
    setEntries(p => { const { [id]: _, ...rest } = p; return rest; });
  }, []);
  const reset = useCallback(() => { seen.current.clear(); setEntries({}); }, []);
  return { entries, load, drop, reset };
}
