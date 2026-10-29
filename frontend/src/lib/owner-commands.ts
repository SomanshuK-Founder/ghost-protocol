import { api, ApiError } from "./api/client.ts";

export type CommandKind =
  "APPROVE" | "REJECT" | "REVOKE" | "CONTINUE" | "CANCEL";
export type CommandRecord = {
  key: string;
  taskRef: string;
  state: "SUBMITTING" | "CONFIRMED" | "UNCERTAIN" | "FAILED";
};
export type CommandStore = Map<string, CommandRecord>;

export function commandBlock(store: CommandStore, taskRef: string) {
  return (
    [...store.values()].find(
      (record) =>
        record.taskRef === taskRef &&
        (record.state === "SUBMITTING" || record.state === "UNCERTAIN"),
    )?.state ?? null
  );
}

export async function runOwnerCommand(
  store: CommandStore,
  input: {
    kind: CommandKind;
    taskRef: string;
    approvalRef?: string;
    csrf: string;
  },
) {
  const blocked = commandBlock(store, input.taskRef);
  if (blocked)
    throw new ApiError(
      409,
      blocked === "UNCERTAIN" ? "COMMAND_UNCERTAIN" : "COMMAND_IN_PROGRESS",
      blocked === "UNCERTAIN",
    );
  const taskCommand = input.kind === "CONTINUE" || input.kind === "CANCEL";
  if (!taskCommand && !input.approvalRef)
    throw new Error("An exact approval reference is required");
  const identity = `${input.kind}:${taskCommand ? input.taskRef : input.approvalRef}`;
  const record = store.get(identity) ?? {
    key: crypto.randomUUID(),
    taskRef: input.taskRef,
    state: "SUBMITTING" as const,
  };
  record.state = "SUBMITTING";
  store.set(identity, record);
  const options = { csrf: input.csrf, key: record.key };
  try {
    if (input.kind === "CONTINUE")
      await api.post(
        "/api/app/v1/tasks/{task_ref}/workflow/continue",
        {},
        { ...options, params: { task_ref: input.taskRef } },
      );
    else if (input.kind === "CANCEL")
      await api.post(
        "/api/app/v1/tasks/{task_ref}/cancel",
        {},
        { ...options, params: { task_ref: input.taskRef } },
      );
    else if (input.kind === "REVOKE")
      await api.post(
        "/api/app/v1/approvals/{approval_ref}/revoke",
        {},
        { ...options, params: { approval_ref: input.approvalRef! } },
      );
    else
      await api.post(
        "/api/app/v1/approvals/{approval_ref}/decision",
        { resolution: input.kind },
        { ...options, params: { approval_ref: input.approvalRef! } },
      );
    record.state = "CONFIRMED";
  } catch (error) {
    record.state =
      error instanceof ApiError && !error.uncertain ? "FAILED" : "UNCERTAIN";
    throw error;
  }
}
