import type { Operation, Schema, TimelineEvent } from "./api/types";

export function validTaskRef(value: string) {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(value);
}
export function localPage<T>(items: T[], requested: number, limit: number) {
  const page = Math.min(
    Math.max(0, requested),
    Math.max(0, Math.ceil(items.length / limit) - 1),
  );
  return {
    items: items.slice(page * limit, (page + 1) * limit),
    page,
    hasNext: (page + 1) * limit < items.length,
  };
}
export function needsReconciliation(
  value: Pick<
    Operation,
    "state" | "execution_status" | "reconciliation_required"
  >,
) {
  return (
    value.reconciliation_required ||
    value.state === "UNKNOWN" ||
    value.state === "DISPATCHING" ||
    value.execution_status === "UNKNOWN"
  );
}
export type Field = {
  label: string;
  value: string | number | boolean | null | undefined;
  copy?: boolean;
};
export function documentFields(document: Schema["DocumentMetadata"]): Field[] {
  return [
    { label: "Resource ID", value: document.resource_id, copy: true },
    { label: "Version reference", value: document.version_ref, copy: true },
    { label: "Display name", value: document.display_name },
    { label: "Classification", value: document.classification },
    { label: "Resource type", value: document.resource_type },
    { label: "Synthetic", value: document.synthetic },
  ];
}
export function eventFields(event: TimelineEvent): Field[] {
  return [
    { label: "Event reference", value: event.event_ref, copy: true },
    { label: "Timestamp", value: event.timestamp },
    { label: "Category", value: event.kind },
    { label: "Task reference", value: event.task_ref, copy: true },
    { label: "Operation reference", value: event.operation_ref, copy: true },
    { label: "Approval reference", value: event.approval_ref, copy: true },
    { label: "Attempt reference", value: event.attempt_ref, copy: true },
    { label: "State", value: event.state },
    { label: "Authorization", value: event.decision },
    { label: "Execution status", value: event.execution_status },
    { label: "Reason", value: event.reason_code },
  ];
}
