import assert from "node:assert/strict";
import { test } from "node:test";
import {
  documentFields,
  eventFields,
  localPage,
  needsReconciliation,
  validTaskRef,
} from "../src/lib/evidence.ts";
import type { Operation, Schema, TimelineEvent } from "../src/lib/api/types.ts";

test("local operation pages are bounded to the returned set, including empty and shrinking sets", () => {
  assert.deepEqual(localPage([1, 2, 3], 0, 2), {
    items: [1, 2],
    page: 0,
    hasNext: true,
  });
  assert.deepEqual(localPage([1, 2, 3], 10, 2), {
    items: [3],
    page: 1,
    hasNext: false,
  });
  assert.deepEqual(localPage([], 10, 2), {
    items: [],
    page: 0,
    hasNext: false,
  });
  assert.deepEqual(localPage([1], -1, 2), {
    items: [1],
    page: 0,
    hasNext: false,
  });
});
test("catalog details whitelist exactly six contracted fields even with unexpected extra data", () => {
  const document = {
    resource_id: "doc_synthetic",
    version_ref: "version_synthetic",
    display_name: "Synthetic brief",
    classification: "PRIVATE_ORIGINAL",
    resource_type: "document",
    synthetic: true,
    raw_content: "must not appear",
    digest: "private",
  } as unknown as Schema["DocumentMetadata"];
  const fields = documentFields(document);
  assert.equal(fields.length, 6);
  assert.equal(fields.filter((field) => field.copy).length, 2);
  assert.doesNotMatch(
    JSON.stringify(fields),
    /must not appear|private|raw_content|digest/,
  );
});
test("audit inspection never spreads uncontracted payloads", () => {
  const event = {
    event_ref: "event_synthetic",
    task_ref: "task_synthetic",
    kind: "EXECUTION_OUTCOME",
    state: "UNKNOWN",
    execution_status: "UNKNOWN",
    raw_payload: "secret body",
  } as unknown as TimelineEvent;
  const fields = eventFields(event);
  assert.equal(
    fields.find((field) => field.label === "State")?.value,
    "UNKNOWN",
  );
  assert.doesNotMatch(JSON.stringify(fields), /secret body|raw_payload/);
});
test("unknown and dispatching evidence requires reconciliation without inventing completion", () => {
  const operation: Pick<
    Operation,
    "state" | "execution_status" | "reconciliation_required"
  > = {
    state: "READY",
    execution_status: "NOT_EXECUTED",
    reconciliation_required: false,
  };
  assert.equal(needsReconciliation(operation), false);
  const changes: Partial<typeof operation>[] = [
    { state: "UNKNOWN" },
    { state: "DISPATCHING" },
    { execution_status: "UNKNOWN" },
    { reconciliation_required: true },
  ];
  for (const change of changes)
    assert.equal(needsReconciliation({ ...operation, ...change }), true);
});
test("task selectors reject path-like or oversized references at the UI boundary", () => {
  assert.equal(validTaskRef("task_synthetic-1"), true);
  for (const value of ["", "../task", "task?owner=other", "a".repeat(65)])
    assert.equal(validTaskRef(value), false);
});
