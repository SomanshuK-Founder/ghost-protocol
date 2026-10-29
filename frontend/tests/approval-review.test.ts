import assert from "node:assert/strict";
import { test } from "node:test";
import {
  approvalBound,
  approvalEligibility,
  continuationEligibility,
  reviewSignature,
} from "../src/lib/approval-review.ts";
import { currentRailStage, railRecord } from "../src/lib/rail-records.ts";
import {
  eventDetail,
  decisionNodes,
  taskState,
} from "../src/lib/presentation.ts";
import { evidence, now, review } from "./review-fixture.ts";

test("exact pending task, operation and request binding permits an owner decision", () => {
  const r = review();
  assert.equal(approvalBound(r), true);
  assert.equal(approvalEligibility(r, "APPROVE", now), null);
  assert.equal(approvalEligibility(r, "REJECT", now), null);
});
test("mismatched task, operation, request, action or purpose fails closed", () => {
  for (const change of ["task_ref", "operation_ref", "request_id"] as const) {
    const r = review();
    r.operation[change] = "foreign_synthetic";
    assert.equal(approvalBound(r), false);
  }
  const r = review();
  r.task.purpose = "prepare_email";
  assert.equal(approvalBound(r), false);
});
test("expired, consumed, in-flight, uncertain or resolved approval cannot be approved", () => {
  const expired = review();
  assert.ok(
    approvalEligibility(
      expired,
      "APPROVE",
      Date.parse(expired.approval.expires_at),
    ),
  );
  for (const field of ["consumed", "in_flight"] as const) {
    const r = review();
    r.approval[field] = true;
    assert.ok(approvalEligibility(r, "APPROVE", now));
  }
  const uncertain = review();
  uncertain.operation.state = "UNKNOWN";
  assert.ok(approvalEligibility(uncertain, "APPROVE", now));
  for (const state of ["APPROVED", "REJECTED", "REVOKED", "EXPIRED"] as const) {
    const r = review();
    r.approval.state = state;
    assert.ok(approvalEligibility(r, "APPROVE", now));
  }
});
test("revocation is available for active pending/approved authority, including in-flight, without promising undo", () => {
  const r = review();
  r.approval.state = "APPROVED";
  r.approval.in_flight = true;
  r.approval.consumed = true;
  assert.equal(approvalEligibility(r, "REVOKE", now), null);
  r.approval.state = "REVOKED";
  assert.ok(approvalEligibility(r, "REVOKE", now));
});
test("a changed reviewed scope or authorization version invalidates confirmation", () => {
  const r = review();
  const signature = reviewSignature(r);
  r.task.authorization_version++;
  assert.notEqual(reviewSignature(r), signature);
  const other = review();
  const original = reviewSignature(other);
  other.approval.binding_digest = "b".repeat(64);
  assert.notEqual(reviewSignature(other), original);
});
test("continuation needs genuine current approved binding plus backend availability", () => {
  const r = review();
  assert.ok(continuationEligibility(evidence(r), now));
  r.approval.state = "APPROVED";
  r.operation.state = "READY";
  r.workflow.continuation_available = true;
  assert.equal(continuationEligibility(evidence(r), now), null);
  r.workflow.operation_ref = "op_foreign";
  assert.match(continuationEligibility(evidence(r), now)!, /binding/);
});
test("rejected, revoked, expired, unknown, started and already-resumed workflows never continue", () => {
  for (const state of ["REJECTED", "REVOKED", "EXPIRED"] as const) {
    const r = review();
    r.approval.state = state;
    r.workflow.continuation_available = true;
    assert.ok(continuationEligibility(evidence(r), now));
  }
  const r = review();
  r.approval.state = "APPROVED";
  r.workflow.continuation_available = true;
  r.operation.execution_status = "SUCCEEDED";
  assert.ok(continuationEligibility(evidence(r), now));
  r.operation.state = "UNKNOWN";
  assert.match(continuationEligibility(evidence(r), now)!, /Reconciliation/);
  r.operation.state = "READY";
  r.operation.execution_status = "NOT_EXECUTED";
  r.workflow.phase = "RESUMED";
  assert.match(continuationEligibility(evidence(r), now)!, /SAFE_STOPPED/);
});
test("rail inspection exposes only present safe records; approval email arguments stay out of audit lens", () => {
  const e = evidence();
  assert.equal(railRecord(e, 2), null);
  assert.equal(railRecord(e, 0)?.task_ref, e.task.task_ref);
  assert.ok(railRecord(e, 4));
  assert.equal(railRecord(e, 3)?.arguments, undefined);
  assert.equal(currentRailStage(e), 3);
  e.workflow.phase = "RESUMED";
  e.approval!.state = "APPROVED";
  assert.equal(currentRailStage(e), 4);
});
test("a later denial takes precedence over historical safe continuation in task summaries", () => {
  const e = evidence();
  e.task.workflow_phase = "RESUMED";
  e.task.operation_state = "DENIED";
  assert.equal(taskState(e.task), "DENIED");
});
test("a denied operation is visually terminal while execution remains NOT_EXECUTED", () => {
  const r = review();
  r.operation.state = "DENIED";
  r.operation.decision = "DENY";
  r.operation.reason_code = "APPROVAL_REVOKED";
  const node = decisionNodes(evidence(r))[5];
  assert.equal(node.state, "denied");
  assert.equal(node.label, "Not executed");
  assert.match(node.detail, /revoked/i);
});
test("audit copy omits absent state/reason fields without inventing an outcome", () => {
  const event = {
    event_ref: "event_synthetic",
    timestamp: "2026-10-29T10:00:00Z",
    kind: "APPROVAL_VIEWED",
    task_ref: "task_synthetic",
    operation_ref: null,
    attempt_ref: null,
    approval_ref: null,
    state: "PENDING",
    decision: null,
    execution_status: null,
    reason_code: null,
  } as const;
  assert.equal(eventDetail(event), "Pending");
  assert.equal(eventDetail({ ...event, state: null }), "Stored backend event");
});
