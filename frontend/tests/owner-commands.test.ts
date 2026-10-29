import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError } from "../src/lib/api/client.ts";
import { commandBlock, runOwnerCommand } from "../src/lib/owner-commands.ts";
import type { CommandStore } from "../src/lib/owner-commands.ts";
const original = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = original;
});
const input = {
  kind: "APPROVE",
  taskRef: "task_synthetic",
  approvalRef: "approval_synthetic",
  csrf: "synthetic",
} as const;
test("approved command sends only resolution, CSRF and stable key; known-error retry retains identity", async () => {
  const keys: string[] = [];
  const store: CommandStore = new Map();
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/app/v1/approvals/approval_synthetic/decision");
    assert.equal(options?.body, '{"resolution":"APPROVE"}');
    keys.push(new Headers(options?.headers).get("Idempotency-Key")!);
    return Response.json(
      { error: { code: "APPROVAL_STATE_CONFLICT" } },
      { status: 409 },
    );
  };
  await assert.rejects(runOwnerCommand(store, input));
  await assert.rejects(runOwnerCommand(store, input));
  assert.equal(keys[0], keys[1]);
  assert.match(keys[0], /^[0-9a-f]{8}-[0-9a-f]{4}-4/);
});
test("lost acknowledgment is uncertain, never retries and locks new decisions after navigation", async () => {
  let calls = 0;
  const store: CommandStore = new Map();
  globalThis.fetch = async () => {
    calls++;
    throw new Error("lost response");
  };
  await assert.rejects(runOwnerCommand(store, input));
  assert.equal(commandBlock(store, input.taskRef), "UNCERTAIN");
  await assert.rejects(
    runOwnerCommand(store, { ...input, kind: "REJECT" }),
    (e: unknown) => e instanceof ApiError && e.uncertain,
  );
  assert.equal(calls, 1);
});
test("concurrent submissions share a task lock; continuation has a distinct explicit request", async () => {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  const store: CommandStore = new Map();
  let calls = 0;
  globalThis.fetch = async (_url, options) => {
    calls++;
    assert.equal(options?.body, "{}");
    await wait;
    return Response.json({ api_version: "ghost-app-v1", data: {} });
  };
  const first = runOwnerCommand(store, { ...input, kind: "CONTINUE" });
  await assert.rejects(runOwnerCommand(store, { ...input, kind: "CONTINUE" }));
  release();
  await first;
  assert.equal(calls, 1);
  assert.equal(commandBlock(store, input.taskRef), null);
});
test("cancellation uses only the exact task, empty body, CSRF and a separate stable command key", async () => {
  const store: CommandStore = new Map();
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/app/v1/tasks/task_synthetic/cancel");
    assert.equal(options?.body, "{}");
    assert.equal(
      new Headers(options?.headers).get("X-Ghost-CSRF"),
      "synthetic",
    );
    assert.ok(new Headers(options?.headers).get("Idempotency-Key"));
    return Response.json({ api_version: "ghost-app-v1", data: {} });
  };
  await runOwnerCommand(store, {
    kind: "CANCEL",
    taskRef: input.taskRef,
    csrf: input.csrf,
  });
  assert.equal(store.get("CANCEL:task_synthetic")?.state, "CONFIRMED");
  assert.equal(store.size, 1);
});
