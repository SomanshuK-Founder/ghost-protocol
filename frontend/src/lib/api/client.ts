import type { paths } from "./schema";
import type { Schema } from "./types";

type GetPath = {
  [P in keyof paths]: P extends `/api/app/v1/${string}`
    ? paths[P] extends { get: unknown }
      ? P
      : never
    : never;
}[keyof paths];
type PostPath = {
  [P in keyof paths]: paths[P] extends { post: unknown } ? P : never;
}[keyof paths];
type ResponseOf<T> = T extends { responses: infer R }
  ? R[keyof R & (200 | 201)] extends {
      content: { "application/json": infer B };
    }
    ? B extends { data: infer D }
      ? D
      : never
    : void
  : never;
type BodyOf<T> = T extends {
  requestBody: { content: { "application/json": infer B } };
}
  ? B
  : never;
type QueryOf<T> = T extends { parameters: { query?: infer Q } }
  ? NonNullable<Q>
  : never;
type ParamsOf<T> = T extends { parameters: { path: infer P } } ? P : never;
type ReadOptions<P extends GetPath> = {
  params?: ParamsOf<paths[P]["get"]>;
  query?: QueryOf<paths[P]["get"]>;
  signal?: AbortSignal;
};
type WriteOptions<P extends PostPath> = {
  params?: ParamsOf<paths[P]["post"]>;
  csrf: string;
} & (paths[P]["post"] extends {
  parameters: { header: { "Idempotency-Key": string } };
}
  ? { key: string }
  : { key?: never });

export class ApiError extends Error {
  status: number;
  code: string;
  uncertain: boolean;
  correlation: string | null;
  constructor(
    status: number,
    code: string,
    uncertain = false,
    correlation: string | null = null,
  ) {
    super(code);
    this.status = status;
    this.code = code;
    this.uncertain = uncertain;
    this.correlation = correlation;
  }
}

function url(path: string, params?: object, query?: object) {
  let resolved = path;
  for (const [name, value] of Object.entries(params ?? {}))
    resolved = resolved.replace(`{${name}}`, encodeURIComponent(String(value)));
  if (resolved.includes("{")) throw new Error("Missing API path reference");
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(query ?? {}))
    if (value !== undefined) search.set(name, String(value));
  return resolved + (search.size ? `?${search}` : "");
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const mutation = init.method === "POST";
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      signal: init.signal
        ? AbortSignal.any([init.signal, AbortSignal.timeout(25_000)])
        : AbortSignal.timeout(25_000),
    });
  } catch {
    throw new ApiError(0, "NETWORK_UNAVAILABLE", mutation);
  }
  if (response.status === 204) return undefined as T;
  let envelope: unknown;
  try {
    envelope = await response.json();
  } catch {
    throw new ApiError(response.status, "INVALID_RESPONSE", mutation);
  }
  if (!response.ok) {
    const error = (envelope as Schema["AppFailure"])?.error;
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      !path.endsWith("/login")
    )
      window.dispatchEvent(new Event("ghost:session-expired"));
    throw new ApiError(
      response.status,
      error?.code ?? "REQUEST_FAILED",
      Boolean(
        error?.command_uncertain ||
        error?.execution_uncertain ||
        error?.reconciliation_required,
      ) ||
        (mutation && response.status >= 500),
      error?.correlation_ref ?? null,
    );
  }
  if (
    !envelope ||
    typeof envelope !== "object" ||
    !("data" in envelope) ||
    !("api_version" in envelope) ||
    envelope.api_version !== "ghost-app-v1"
  )
    throw new ApiError(response.status, "INVALID_RESPONSE", mutation);
  return envelope.data as T;
}

// No mutation retry: an absent acknowledgment can still mean a committed command.
export const api = {
  get<P extends GetPath>(
    path: P,
    options: ReadOptions<P> = {},
  ): Promise<ResponseOf<paths[P]["get"]>> {
    return request(url(path, options.params, options.query), {
      method: "GET",
      signal: options.signal,
    });
  },
  post<P extends PostPath>(
    path: P,
    body: BodyOf<paths[P]["post"]>,
    options: WriteOptions<P>,
  ): Promise<ResponseOf<paths[P]["post"]>> {
    return request(url(path, options.params), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Ghost-CSRF": options.csrf,
        ...(options.key ? { "Idempotency-Key": options.key } : {}),
      },
      body: JSON.stringify(body),
    });
  },
};
