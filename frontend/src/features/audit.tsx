"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { validTaskRef } from "@/lib/evidence";
import { taskTitle } from "@/lib/presentation";
import { useCursorPage } from "@/lib/use-cursor-page";
import { useResource } from "@/lib/use-resource";
import { AuditEvents } from "@/components/audit-events";
import { PageControls } from "@/components/evidence-ui";
import { TaskScopePicker } from "@/components/task-scope-picker";
import {
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";

export function AuditExplorer() {
  const ref = useSearchParams().get("ref") ?? "";
  const router = useRouter();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">THE DURABLE RECORD</p>
          <h1>Every decision, in context.</h1>
          <p>Genuine task-scoped events, ordered from oldest to newest.</p>
        </div>
      </div>
      <TaskScopePicker
        value={ref}
        onChange={(value) =>
          router.replace(
            value ? `/audit/?ref=${encodeURIComponent(value)}` : "/audit/",
          )
        }
      />
      {ref ? (
        <AuditForTask key={ref} reference={ref} />
      ) : (
        <section className="panel">
          <EmptyState title="Choose a task to inspect its history">
            The audit explorer never combines unscoped events or fabricates a
            trace.
          </EmptyState>
        </section>
      )}
    </>
  );
}
function AuditForTask({ reference }: { reference: string }) {
  const page = useCursorPage();
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!validTaskRef(reference)) throw new ApiError(404, "NOT_FOUND");
      const params = { task_ref: reference };
      const [task, timeline] = await Promise.all([
        api.get("/api/app/v1/tasks/{task_ref}", { params, signal }),
        api.get("/api/app/v1/tasks/{task_ref}/timeline", {
          params,
          query: { limit: page.limit, cursor: page.cursor },
          signal,
        }),
      ]);
      return { task, ...timeline };
    },
    [reference, page.limit, page.cursor],
  );
  const { data, error, loading, refresh } = useResource(load);
  return (
    <>
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
          <div className="mode-strip">
            <span>
              <ShieldCheck size={16} />
              {taskTitle(data.task)} · Stored backend events
            </span>
            <span>No prompts, email bodies, or raw document content</span>
          </div>
          <section className="panel audit-explorer-panel">
            <div className="section-heading">
              <div>
                <h2>Chronological timeline</h2>
                <p className="field-help">
                  Snapshot <Timestamp value={data.snapshot_at} />
                </p>
              </div>
              <Button
                variant="secondary"
                onClick={() => {
                  page.first();
                  refresh();
                }}
              >
                <RefreshCw size={15} />
                Refresh timeline
              </Button>
            </div>
            {data.items.length ? (
              <AuditEvents events={data.items} />
            ) : (
              <EmptyState title="No visible events in this page">
                Only correlated, owner-safe backend events are returned.
                Continue through available cursor pages if present.
              </EmptyState>
            )}
          </section>
          <PageControls
            limit={page.limit}
            onLimit={page.changeLimit}
            onFirst={page.first}
            onNext={() => page.next(data.next_cursor)}
            hasNext={Boolean(data.next_cursor)}
            first={!page.cursor}
            label="Events per page"
          />
        </>
      ) : null}
    </>
  );
}
