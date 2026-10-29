"use client";
import { useState } from "react";
export function useCursorPage(defaultLimit = 10) {
  const [page, setPage] = useState<{ limit: number; cursor?: string }>({
    limit: defaultLimit,
  });
  return {
    ...page,
    first: () => setPage((current) => ({ limit: current.limit })),
    next: (cursor: string | null) => {
      if (cursor) setPage((current) => ({ ...current, cursor }));
    },
    changeLimit: (limit: number) => setPage({ limit }),
  };
}
