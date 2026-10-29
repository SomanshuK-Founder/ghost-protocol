import type {
  Approval,
  Operation,
  Planning,
  Task,
  TaskDetail,
  TimelineEvent,
  Workflow,
} from "./api/types";

export const profiles = {
  document_simulation_v1: {
    title: "Document assistant",
    description:
      "Plan a synthetic document summary. No document content is read.",
  },
  email_draft_v1: {
    title: "Email draft",
    description: "Review a scoped email draft plan. No message is submitted.",
  },
  email_send_v1: {
    title: "Email authorization review",
    description:
      "Review a fixed synthetic email proposal. The browser cannot dispatch it.",
  },
} as const;

export function taskTitle(task: Task) {
  return profiles[task.profile_id]?.title ?? "Unknown task profile";
}
export function readable(value: string | null | undefined) {
  return value
    ? value
        .replaceAll("_", " ")
        .toLowerCase()
        .replace(/^./, (c) => c.toUpperCase())
    : "Not recorded";
}
export function eventDetail(event: TimelineEvent) {
  return (
    [event.state ?? event.decision, event.reason_code]
      .filter((value): value is NonNullable<typeof value> => value !== null)
      .map(readable)
      .join(" · ") || "Stored backend event"
  );
}
export function taskState(task: Task) {
  if (task.authority_state !== "OPEN") return task.authority_state;
  if (task.operation_state === "UNKNOWN" || task.planning_state === "UNCERTAIN")
    return "RECONCILIATION_REQUIRED";
  if (["DENIED", "SUCCEEDED", "FAILED"].includes(task.operation_state ?? ""))
    return task.operation_state!;
  if (task.workflow_phase === "RESUMED") return "SAFE_STOPPED";
  if (
    task.operation_state === "READY" &&
    ["PAUSED", "ADMITTED"].includes(task.workflow_phase ?? "")
  )
    return "AWAITING_CONTINUATION";
  if (task.operation_state) return task.operation_state;
  return task.planning_state === "NOT_STARTED"
    ? "CREATED"
    : task.planning_state;
}

export type RailState =
  "complete" | "active" | "blocked" | "denied" | "uncertain" | "unverified";
export type RailNode = {
  title: string;
  state: RailState;
  label: string;
  detail: string;
  timestamp?: string | null;
  reference?: string | null;
};
export type Evidence = {
  task: TaskDetail;
  planning: Planning;
  approval?: Approval | null;
  workflow: Workflow;
  operations: Operation[];
  timeline: TimelineEvent[];
};

export function decisionNodes({
  task,
  planning,
  approval,
  workflow,
  operations,
  timeline,
}: Evidence): RailNode[] {
  const last = (kind: TimelineEvent["kind"]) =>
    timeline.filter((e) => e.kind === kind).at(-1);
  const auth = last("AUTHORIZATION");
  const human = last("APPROVAL_TRANSITION");
  const continuation = last("WORKFLOW_TRANSITION");
  const operation =
    operations.find((o) => o.operation_ref === planning.operation_ref) ??
    operations[0];
  const uncertain =
    task.operation_state === "UNKNOWN" ||
    operation?.reconciliation_required ||
    workflow.reconciliation_required ||
    planning.state === "UNCERTAIN";
  const decision = planning.authorization_decision ?? auth?.decision;
  const humanState = approval?.state ?? human?.state;
  return [
    {
      title: "Task",
      state: "complete",
      label: "Request recorded",
      detail: "Owner-scoped task",
      timestamp: task.created_at,
      reference: task.task_ref,
    },
    {
      title: "Planning",
      state:
        planning.state === "FINISHED"
          ? "complete"
          : planning.state === "RUNNING"
            ? "active"
            : planning.state === "UNCERTAIN"
              ? "uncertain"
              : planning.state === "FAILED"
                ? "denied"
                : "unverified",
      label: readable(planning.state),
      detail:
        planning.provenance.planning_source === "MOCK_MODEL"
          ? "Simulated · mock model"
          : readable(planning.provenance.planning_source),
      timestamp: planning.finished_at ?? planning.started_at,
      reference: planning.planning_ref,
    },
    {
      title: "Authorization",
      state:
        decision === "DENY"
          ? "denied"
          : decision === "APPROVAL_REQUIRED"
            ? "blocked"
            : decision === "ALLOW"
              ? "complete"
              : "unverified",
      label: decision ? readable(decision) : "Not verified",
      detail: decision
        ? readable(planning.reason_code ?? auth?.reason_code)
        : "Gateway decision not recorded",
      timestamp: auth?.timestamp,
      reference: auth?.event_ref,
    },
    {
      title: "Human decision",
      state:
        humanState === "APPROVED"
          ? "complete"
          : ["REJECTED", "REVOKED", "EXPIRED"].includes(humanState ?? "")
            ? "denied"
            : humanState === "PENDING" || planning.approval_ref
              ? "blocked"
              : "unverified",
      label: humanState
        ? readable(humanState)
        : planning.approval_ref
          ? "Awaiting decision"
          : "Not recorded",
      detail: "Approval does not execute an action",
      timestamp: human?.timestamp,
      reference: approval?.approval_ref ?? planning.approval_ref,
    },
    {
      title: "Safe continuation",
      state: uncertain
        ? "uncertain"
        : workflow.phase === "RESUMED"
          ? "complete"
          : workflow.phase === "DENIED"
            ? "denied"
            : workflow.phase
              ? "blocked"
              : "unverified",
      label: uncertain
        ? "Reconciliation required"
        : workflow.phase === "RESUMED"
          ? "SAFE_STOPPED"
          : readable(workflow.phase),
      detail:
        workflow.phase === "RESUMED"
          ? "Continuation ended · no browser dispatch"
          : "Separate explicit continuation required",
      timestamp: continuation?.timestamp,
      reference: continuation?.event_ref,
    },
    {
      title: "Operation outcome",
      state:
        uncertain || operation?.execution_status === "UNKNOWN"
          ? "uncertain"
          : operation?.execution_status === "FAILED"
            ? "denied"
            : operation?.state === "DENIED"
              ? "denied"
              : operation?.execution_status === "SUCCEEDED"
                ? "complete"
                : "unverified",
      label: uncertain
        ? "Unknown · inspect records"
        : operation
          ? readable(operation.execution_status)
          : "Not recorded",
      detail: operation
        ? operation.state === "DENIED"
          ? `${readable(operation.reason_code)} · ${readable(operation.provenance.effect)}`
          : `${readable(operation.provenance.effect)} · ${readable(operation.provenance.evidence)}`
        : "No execution evidence",
      timestamp: operation?.updated_at,
      reference: operation?.operation_ref,
    },
  ];
}
