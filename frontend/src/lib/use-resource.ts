"use client";
import { useCallback, useEffect, useState } from "react";

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<{
    load: typeof load;
    revision: number;
    data: T | null;
    error: unknown;
  } | null>(null);
  const refresh = useCallback(() => setRevision((r) => r + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    load(controller.signal)
      .then((data) => {
        if (active) setResult({ load, revision, data, error: null });
      })
      .catch((error: unknown) => {
        if (active) setResult({ load, revision, data: null, error });
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [load, revision]);
  const current = result?.load === load && result.revision === revision;
  return {
    data: result?.load === load ? result.data : null,
    error: current ? result.error : null,
    loading: !current,
    refresh,
    replace: (data: T) => setResult({ load, revision, data, error: null }),
  };
}
