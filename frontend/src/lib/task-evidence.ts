import { api } from "./api/client";
import type { Evidence } from "./presentation";
export async function loadEvidence(
  taskRef: string,
  signal?: AbortSignal,
): Promise<Evidence> {
  const options = { params: { task_ref: taskRef }, signal };
  const [task, planning, workflow, operations, timeline] = await Promise.all([
    api.get("/api/app/v1/tasks/{task_ref}", options),
    api.get("/api/app/v1/tasks/{task_ref}/planning", options),
    api.get("/api/app/v1/tasks/{task_ref}/workflow", options),
    api.get("/api/app/v1/tasks/{task_ref}/operations", options),
    api.get("/api/app/v1/tasks/{task_ref}/timeline", {
      ...options,
      query: { limit: 50 },
    }),
  ]);
  const approval = task.approval_ref
    ? await api.get("/api/app/v1/approvals/{approval_ref}", {
        params: { approval_ref: task.approval_ref },
        signal,
      })
    : null;
  return {
    task,
    planning,
    workflow,
    operations: operations.items,
    timeline: timeline.items,
    approval,
  };
}
