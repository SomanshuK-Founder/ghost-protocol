import assert from "node:assert/strict";
import { test } from "node:test";
import { decisionNodes, taskState } from "../src/lib/presentation.ts";
import type { Evidence } from "../src/lib/presentation.ts";
import type { Operation, Provenance } from "../src/lib/api/types.ts";

const provenance: Provenance = {
  environment: "OFFLINE_DEMO",
  planning_source: "MOCK_MODEL",
  execution_mode: null,
  effect: "NONE",
  evidence: "OBSERVED",
};
const timestamp = "2026-10-29T10:00:00Z";
function evidence(): Evidence {
  return {
    task: {
      task_ref: "task_synthetic",
      profile_id: "document_simulation_v1",
      authority_state: "OPEN",
      created_at: timestamp,
      expires_at: timestamp,
      planning_state: "NOT_STARTED",
      approval_ref: null,
      workflow_phase: null,
      operation_state: null,
      provenance,
      purpose: "summarize_document",
      resource_ids: ["doc_synthetic"],
      allowed_action: "files.read",
      authorization_version: 0,
      in_flight: false,
      reconciliation_required: false,
    },
    planning: {
      task_ref: "task_synthetic",
      planning_ref: null,
      state: "NOT_STARTED",
      outcome: null,
      intent: null,
      proposed_actions: [],
      authorization_decision: null,
      reason_code: null,
      request_id: null,
      operation_ref: null,
      approval_ref: null,
      error_code: null,
      started_at: null,
      finished_at: null,
      provenance,
    },
    workflow: {
      task_ref: "task_synthetic",
      binding_ref: null,
      operation_ref: null,
      approval_ref: null,
      phase: null,
      authorization_version: 0,
      expires_at: null,
      continuation_available: false,
      reconciliation_required: false,
      provenance,
    },
    operations: [],
    timeline: [],
    approval: null,
  };
}
function operation(status: Operation["execution_status"]): Operation {
  return {
    operation_ref: "op_synthetic",
    task_ref: "task_synthetic",
    request_id: "request_synthetic",
    action: "files.read",
    state: status === "NOT_EXECUTED" ? "READY" : status,
    decision: "ALLOW",
    execution_status: status,
    reason_code: "EXECUTION_NOT_STARTED",
    approval_ref: null,
    approval_state: null,
    attempt_ref: null,
    audit_event_ref: "event_synthetic",
    revision: 1,
    created_at: timestamp,
    updated_at: timestamp,
    reconciliation_required: status === "UNKNOWN",
    provenance: {
      ...provenance,
      execution_mode: "SIMULATED",
      effect: "UNCONFIRMED",
      evidence: "UNATTESTED",
    },
  };
}
test("new task completes only the recorded request stage", () => {
  const nodes = decisionNodes(evidence());
  assert.deepEqual(
    nodes.map((n) => n.state),
    [
      "complete",
      "unverified",
      "unverified",
      "unverified",
      "unverified",
      "unverified",
    ],
  );
  assert.equal(nodes[0].timestamp, timestamp);
  assert.equal(nodes[2].timestamp, undefined);
});
test("approval required blocks and never implies execution", () => {
  const e = evidence();
  e.planning.authorization_decision = "APPROVAL_REQUIRED";
  e.planning.approval_ref = "approval_synthetic";
  e.planning.state = "FINISHED";
  const nodes = decisionNodes(e);
  assert.equal(nodes[2].state, "blocked");
  assert.equal(nodes[3].state, "blocked");
  assert.equal(nodes[5].label, "Not recorded");
});
test("ALLOW and human approval do not complete continuation or execution", () => {
  const e = evidence();
  e.planning.authorization_decision = "ALLOW";
  e.approval = {
    approval_ref: "approval_synthetic",
    task_ref: "task_synthetic",
    operation_ref: "op_synthetic",
    request_id: "request_synthetic",
    state: "APPROVED",
    expires_at: timestamp,
  };
  const nodes = decisionNodes(e);
  assert.equal(nodes[2].state, "complete");
  assert.equal(nodes[3].state, "complete");
  assert.equal(nodes[4].state, "unverified");
  assert.equal(nodes[5].state, "unverified");
});
test("denial, rejection, revocation, and expiry remain distinct blocked outcomes", () => {
  for (const state of ["REJECTED", "REVOKED", "EXPIRED"] as const) {
    const e = evidence();
    e.planning.authorization_decision = "DENY";
    e.approval = {
      approval_ref: "approval_synthetic",
      task_ref: "task_synthetic",
      operation_ref: "op_synthetic",
      request_id: "request_synthetic",
      state,
      expires_at: timestamp,
    };
    const nodes = decisionNodes(e);
    assert.equal(nodes[2].state, "denied");
    assert.equal(nodes[3].state, "denied");
    assert.match(nodes[3].label.toUpperCase(), new RegExp(state));
  }
});
test("RESUMED maps to SAFE_STOPPED without completing execution", () => {
  const e = evidence();
  e.workflow.phase = "RESUMED";
  e.task.workflow_phase = "RESUMED";
  assert.equal(decisionNodes(e)[4].label, "SAFE_STOPPED");
  assert.equal(decisionNodes(e)[5].state, "unverified");
  assert.equal(taskState(e.task), "SAFE_STOPPED");
});
test("unknown outcome overrides continuation and requires reconciliation", () => {
  const e = evidence();
  e.workflow.phase = "RESUMED";
  e.task.operation_state = "UNKNOWN";
  e.operations = [operation("UNKNOWN")];
  assert.equal(decisionNodes(e)[4].state, "uncertain");
  assert.equal(decisionNodes(e)[5].state, "uncertain");
  assert.equal(taskState(e.task), "RECONCILIATION_REQUIRED");
});
test("recorded success preserves unattested unconfirmed provenance", () => {
  const e = evidence();
  e.operations = [operation("SUCCEEDED")];
  const outcome = decisionNodes(e)[5];
  assert.equal(outcome.label, "Succeeded");
  assert.equal(outcome.detail, "Unconfirmed · Unattested");
  assert.doesNotMatch(outcome.detail, /delivered|sent|read confirmed/i);
});
