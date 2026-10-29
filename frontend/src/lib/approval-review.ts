import { api } from "./api/client.ts";
import type {
  ApprovalDetail,
  Operation,
  TaskDetail,
  Workflow,
  Schema,
} from "./api/types";
import type { Evidence } from "./presentation";

export type ApprovalReview = {
  approval: ApprovalDetail;
  task: TaskDetail;
  operation: Operation;
  workflow: Workflow;
  document?: Schema["DocumentMetadata"] | null;
};

export async function loadApprovalReview(
  reference: string,
  signal?: AbortSignal,
): Promise<ApprovalReview> {
  const approval = await api.get("/api/app/v1/approvals/{approval_ref}", {
    params: { approval_ref: reference },
    signal,
  });
  const params = { task_ref: approval.task_ref };
  const [task, operation, workflow, catalog] = await Promise.all([
    api.get("/api/app/v1/tasks/{task_ref}", { params, signal }),
    api.get("/api/app/v1/tasks/{task_ref}/operations/{operation_ref}", {
      params: { ...params, operation_ref: approval.operation_ref },
      signal,
    }),
    api.get("/api/app/v1/tasks/{task_ref}/workflow", { params, signal }),
    "resource_id" in approval.arguments
      ? api.get("/api/app/v1/documents", { query: { limit: 50 }, signal })
      : Promise.resolve(null),
  ]);
  const pin = approval.resource_versions[0];
  const document =
    catalog?.items.find(
      (item) =>
        item.resource_id === pin?.resource_id &&
        item.version_ref === pin?.version_ref,
    ) ?? null;
  return { approval, task, operation, workflow, document };
}

export function approvalBound({
  approval: a,
  task: t,
  operation: o,
}: ApprovalReview) {
  const resourceBound =
    "resource_id" in a.arguments
      ? t.resource_ids.includes(a.arguments.resource_id) &&
        a.resource_versions.length === 1 &&
        a.resource_versions[0].resource_id === a.arguments.resource_id
      : a.resource_versions.every((v) =>
          t.resource_ids.includes(v.resource_id),
        );
  return (
    resourceBound &&
    a.task_ref === t.task_ref &&
    o.task_ref === t.task_ref &&
    t.approval_ref === a.approval_ref &&
    o.approval_ref === a.approval_ref &&
    o.operation_ref === a.operation_ref &&
    o.request_id === a.request_id &&
    o.action === a.action &&
    t.allowed_action === a.action &&
    t.purpose === a.purpose
  );
}

export function approvalEligibility(
  review: ApprovalReview,
  kind: "APPROVE" | "REJECT" | "REVOKE",
  now: number,
) {
  if (!approvalBound(review))
    return "The task and operation binding could not be verified.";
  const { approval, task, operation } = review;
  if (
    now >= Date.parse(approval.expires_at) ||
    now >= Date.parse(task.expires_at)
  )
    return "The review window has expired. Refresh the server record.";
  if (kind === "REVOKE")
    return ["PENDING", "APPROVED"].includes(approval.state)
      ? null
      : "There is no active permission to revoke.";
  if (task.authority_state !== "OPEN") return "This task is no longer open.";
  if (approval.state !== "PENDING")
    return "This approval has already been resolved.";
  if (
    approval.consumed ||
    approval.in_flight ||
    task.in_flight ||
    task.reconciliation_required ||
    operation.reconciliation_required ||
    ["DISPATCHING", "UNKNOWN"].includes(operation.state)
  )
    return "The operation requires reconciliation. Do not submit another decision.";
  return null;
}

export function reviewSignature(review: ApprovalReview) {
  return JSON.stringify([
    review.approval,
    review.task.authority_state,
    review.task.authorization_version,
    review.operation.state,
    review.operation.revision,
    review.workflow,
  ]);
}

export function continuationEligibility(evidence: Evidence, now: number) {
  const { task, workflow, approval, operations } = evidence;
  if (
    task.reconciliation_required ||
    workflow.reconciliation_required ||
    operations.some(
      (o) =>
        o.reconciliation_required ||
        ["UNKNOWN", "DISPATCHING"].includes(o.state),
    )
  )
    return "Reconciliation required. Continuation is blocked; do not retry execution.";
  if (workflow.phase === "RESUMED")
    return "SAFE_STOPPED. Continuation ended without browser dispatch.";
  if (task.authority_state !== "OPEN" || now >= Date.parse(task.expires_at))
    return "The task is no longer active.";
  if (!approval || approval.state !== "APPROVED")
    return "An active human approval is required before continuation.";
  if (
    now >= Date.parse(approval.expires_at) ||
    (workflow.expires_at && now >= Date.parse(workflow.expires_at))
  )
    return "The approval or continuation window has expired.";
  const operation = operations.find(
    (o) => o.operation_ref === workflow.operation_ref,
  );
  if (
    workflow.task_ref !== task.task_ref ||
    approval.task_ref !== task.task_ref ||
    workflow.approval_ref !== approval.approval_ref ||
    task.approval_ref !== approval.approval_ref ||
    !operation ||
    operation.task_ref !== task.task_ref ||
    operation.approval_ref !== approval.approval_ref ||
    operation.request_id !== approval.request_id ||
    operation.operation_ref !== approval.operation_ref
  )
    return "The current workflow binding could not be verified.";
  if (task.in_flight || operation.execution_status !== "NOT_EXECUTED")
    return "An operation has already started or has an uncertain outcome. Inspect its records.";
  if (
    !workflow.continuation_available ||
    !["PAUSED", "ADMITTED"].includes(workflow.phase ?? "")
  )
    return "The backend has not made this workflow available for continuation.";
  return null;
}

export function continuationSignature(e: Evidence) {
  return JSON.stringify([
    e.task.task_ref,
    e.task.authority_state,
    e.task.authorization_version,
    e.task.in_flight,
    e.task.reconciliation_required,
    e.workflow,
    e.approval
      ? [
          e.approval.approval_ref,
          e.approval.state,
          e.approval.expires_at,
          e.approval.request_id,
        ]
      : null,
    e.operations.map((o) => [
      o.operation_ref,
      o.revision,
      o.state,
      o.execution_status,
    ]),
  ]);
}
