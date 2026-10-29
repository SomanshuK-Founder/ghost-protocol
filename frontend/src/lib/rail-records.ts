import type { Evidence } from "./presentation";

export function railRecord(
  e: Evidence,
  index: number,
): Record<string, unknown> | null {
  const last = (kind: Evidence["timeline"][number]["kind"]) =>
    e.timeline.filter((event) => event.kind === kind).at(-1);
  if (index === 0)
    return {
      task_ref: e.task.task_ref,
      profile_id: e.task.profile_id,
      authority_state: e.task.authority_state,
      created_at: e.task.created_at,
      expires_at: e.task.expires_at,
    };
  if (index === 1)
    return e.planning.planning_ref
      ? {
          planning_ref: e.planning.planning_ref,
          state: e.planning.state,
          outcome: e.planning.outcome,
          intent: e.planning.intent,
          proposed_actions: e.planning.proposed_actions,
          started_at: e.planning.started_at,
          finished_at: e.planning.finished_at,
          provenance: e.planning.provenance,
        }
      : null;
  if (index === 2) return last("AUTHORIZATION") ?? null;
  if (index === 3)
    return e.approval
      ? {
          approval_ref: e.approval.approval_ref,
          task_ref: e.approval.task_ref,
          operation_ref: e.approval.operation_ref,
          request_id: e.approval.request_id,
          state: e.approval.state,
          expires_at: e.approval.expires_at,
        }
      : (last("APPROVAL_TRANSITION") ?? null);
  if (index === 4) return e.workflow.binding_ref ? { ...e.workflow } : null;
  return (
    e.operations.find(
      (operation) => operation.operation_ref === e.planning.operation_ref,
    ) ?? null
  );
}

export function currentRailStage(e: Evidence) {
  if (
    e.task.reconciliation_required ||
    e.workflow.reconciliation_required ||
    e.operations.some((o) => o.state === "UNKNOWN" || o.reconciliation_required)
  )
    return 5;
  if (
    e.planning.state === "NOT_STARTED" ||
    e.planning.state === "RUNNING" ||
    e.planning.state === "FAILED" ||
    e.planning.state === "UNCERTAIN"
  )
    return 1;
  if (
    e.approval?.state === "PENDING" ||
    ["REJECTED", "REVOKED", "EXPIRED"].includes(e.approval?.state ?? "")
  )
    return 3;
  if (e.planning.authorization_decision === "DENY") return 2;
  if (e.workflow.phase) return 4;
  return 5;
}
