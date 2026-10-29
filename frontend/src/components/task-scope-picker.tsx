"use client";
import { useCallback, useId, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import { validTaskRef } from "@/lib/evidence";
import { taskTitle } from "@/lib/presentation";
import { useCursorPage } from "@/lib/use-cursor-page";
import { useResource } from "@/lib/use-resource";
import { PageControls } from "./evidence-ui";
import { EmptyState, ErrorPanel, LoadingSkeleton } from "./ui";

export function TaskScopePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const [browse, setBrowse] = useState(false);
  const page = useCursorPage();
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (value && !validTaskRef(value)) throw new ApiError(404, "NOT_FOUND");
      const tasks = await api.get("/api/app/v1/tasks", {
        query: { limit: page.limit, cursor: page.cursor },
        signal,
      });
      const selected =
        value && !tasks.items.some((task) => task.task_ref === value)
          ? await api.get("/api/app/v1/tasks/{task_ref}", {
              params: { task_ref: value },
              signal,
            })
          : null;
      return { ...tasks, selected };
    },
    [page.limit, page.cursor, value],
  );
  const { data, error, loading, refresh } = useResource(load);
  return (
    <section
      className="panel task-scope-panel"
      aria-label="Task scope selector"
    >
      {error ? (
        <ErrorPanel
          error={error}
          onRetry={() => {
            page.first();
            refresh();
          }}
        />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <label htmlFor={id}>Task scope</label>
          <select
            id={id}
            value={value}
            onChange={(event) => onChange(event.target.value)}
          >
            <option value="">Choose an owned task</option>
            {data.selected ? (
              <option value={data.selected.task_ref}>
                {taskTitle(data.selected)} · {data.selected.task_ref.slice(-8)}{" "}
                (selected)
              </option>
            ) : null}
            {data.items.map((task) => (
              <option key={task.task_ref} value={task.task_ref}>
                {taskTitle(task)} · {task.task_ref.slice(-8)}
              </option>
            ))}
          </select>
          <p className="field-help">
            Only owned application tasks are listed. References identify
            records; they grant no authority.
          </p>
          {!data.items.length ? (
            <EmptyState title="No tasks in this page">
              Create a scoped task to begin its operation and audit history.
            </EmptyState>
          ) : null}
          <details className="technical-details" open={browse}>
            <summary
              onClick={(event) => {
                event.preventDefault();
                setBrowse((current) => !current);
              }}
            >
              Browse task pages
            </summary>
            <PageControls
              limit={page.limit}
              onLimit={page.changeLimit}
              onFirst={page.first}
              onNext={() => page.next(data.next_cursor)}
              hasNext={Boolean(data.next_cursor)}
              first={!page.cursor}
              label="Tasks per page"
            />
          </details>
        </>
      ) : null}
    </section>
  );
}
