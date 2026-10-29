import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api, ApiError } from "../src/lib/api/client.ts";
const original = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = original;
});
test("same-origin session read never sends bearer credentials", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/app/v1/session");
    assert.equal(options?.credentials, "same-origin");
    assert.equal(options?.cache, "no-store");
    assert.equal(options?.headers, undefined);
    return Response.json({
      api_version: "ghost-app-v1",
      data: { authenticated: false },
      replayed: false,
    });
  };
  assert.equal((await api.get("/api/app/v1/session")).authenticated, false);
});
test("mutation forwards only CSRF, canonical key, and exact payload", async () => {
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/app/v1/tasks/task_demo/planning");
    assert.deepEqual(options?.headers, {
      "Content-Type": "application/json",
      "X-Ghost-CSRF": "synthetic",
      "Idempotency-Key": "c22e6127-78ea-447c-a5ca-8c206550df6f",
    });
    assert.equal(
      options?.body,
      JSON.stringify({ user_request: "Synthetic request" }),
    );
    return Response.json({
      api_version: "ghost-app-v1",
      data: { state: "FINISHED" },
    });
  };
  await api.post(
    "/api/app/v1/tasks/{task_ref}/planning",
    { user_request: "Synthetic request" },
    {
      params: { task_ref: "task_demo" },
      csrf: "synthetic",
      key: "c22e6127-78ea-447c-a5ca-8c206550df6f",
    },
  );
});
test("network loss never retries a mutation and marks outcome uncertain", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    throw new Error("connection lost");
  };
  await assert.rejects(
    api.post(
      "/api/app/v1/tasks",
      { profile_id: "email_draft_v1", resource_id: null },
      { csrf: "synthetic", key: crypto.randomUUID() },
    ),
    (error: unknown) => error instanceof ApiError && error.uncertain,
  );
  assert.equal(calls, 1);
});
test("409 and backend uncertainty are preserved without retry", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return Response.json(
      {
        error: {
          code: "COMMAND_UNCERTAIN",
          command_uncertain: true,
          correlation_ref: "http_demo",
        },
      },
      { status: 409 },
    );
  };
  await assert.rejects(
    api.post(
      "/api/app/v1/tasks",
      { profile_id: "email_draft_v1", resource_id: null },
      { csrf: "synthetic", key: crypto.randomUUID() },
    ),
    (error: unknown) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.uncertain &&
      error.correlation === "http_demo",
  );
  assert.equal(calls, 1);
});
test("logout has an empty JSON body and no idempotency key", async () => {
  globalThis.fetch = async (_url, options) => {
    assert.equal(options?.body, "{}");
    assert.ok(!("Idempotency-Key" in (options?.headers ?? {})));
    return new Response(null, { status: 204 });
  };
  assert.equal(
    await api.post("/api/app/v1/session/logout", {}, { csrf: "synthetic" }),
    undefined,
  );
});
test("cursor is passed as opaque encoded query data", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/api/app/v1/tasks?limit=20&cursor=opaque%2B%2F%3D");
    return Response.json({
      api_version: "ghost-app-v1",
      data: { items: [], next_cursor: null },
    });
  };
  await api.get("/api/app/v1/tasks", {
    query: { limit: 20, cursor: "opaque+/=" },
  });
});
test("invalid success envelopes are explicit errors", async () => {
  globalThis.fetch = async () => Response.json({ success: true });
  await assert.rejects(
    api.get("/api/app/v1/session"),
    (error: unknown) =>
      error instanceof ApiError && error.code === "INVALID_RESPONSE",
  );
});
