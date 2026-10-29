"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { taskTitle } from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import {
  Badge,
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";
import { ApprovalExpiry } from "@/components/review-primitives";

export function ApprovalCenter() {
  const [cursor, setCursor] = useState<string | undefined>();
  const load = useCallback(
    async (signal: AbortSignal) => {
      const page = await api.get("/api/app/v1/tasks", {
        query: { limit: 20, cursor },
        signal,
      });
      const queues = await Promise.all(
        page.items
          .filter((t) => t.approval_ref)
          .map(async (task) => {
            const queue = await api.get("/api/app/v1/approvals", {
              query: { task_ref: task.task_ref },
              signal,
            });
            return queue.items.map((approval) => ({ approval, task }));
          }),
      );
      return { page, items: queues.flat() };
    },
    [cursor],
  );
  const { data, loading, error, refresh } = useResource(load);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">THE HUMAN CHECKPOINT</p>
          <h1>
            Your permission.
            <br />
            Precisely scoped.
          </h1>
          <p>Inspect the exact request. Make a deliberate decision.</p>
        </div>
        <Button variant="secondary" onClick={refresh} disabled={loading}>
          <RefreshCw size={16} />
          Refresh approvals
        </Button>
      </div>
      <div className="mode-strip">
        <span>
          <ShieldCheck size={16} />
          Approval records permission
        </span>
        <span>Continuation is separate. No browser dispatch.</span>
      </div>
      {error ? (
        <ErrorPanel
          error={error}
          onRetry={() => {
            setCursor(undefined);
            refresh();
          }}
        />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <div className="section-heading">
            <div>
              <h2>
                Pending approvals{" "}
                <span className="queue-count">{data.items.length}</span>
              </h2>
              <p className="field-help">
                For {data.page.items.length} tasks in this page ·{" "}
                <Timestamp value={data.page.snapshot_at} />
              </p>
            </div>
          </div>
          <div className="approval-queue">
            {data.items.length ? (
              data.items.map(({ approval, task }) => (
                <article
                  className="panel approval-queue-card"
                  key={approval.approval_ref}
                >
                  <div className="queue-card-heading">
                    <Badge value={approval.state} />
                    <ApprovalExpiry value={approval.expires_at} />
                  </div>
                  <h3>{taskTitle(task)}</h3>
                  <p>
                    One task. One operation. An exact scope for you to review.
                  </p>
                  <Link
                    className="button secondary"
                    href={`/approvals/detail/?ref=${encodeURIComponent(approval.approval_ref)}`}
                  >
                    Inspect request <ArrowUpRight size={16} />
                  </Link>
                  <Link
                    className="text-link"
                    href={`/tasks/detail/?ref=${encodeURIComponent(task.task_ref)}`}
                  >
                    Task workspace <ArrowRight size={15} />
                  </Link>
                </article>
              ))
            ) : (
              <section className="panel">
                <EmptyState
                  title="No pending decisions in this page"
                  action={
                    <Link className="button secondary" href="/tasks/">
                      Open tasks <ArrowRight size={16} />
                    </Link>
                  }
                >
                  Resolved and expired reviews leave the pending queue. Their
                  records remain available from the task workspace.
                </EmptyState>
              </section>
            )}
          </div>
          <div className="pagination">
            <p>Task-page scope · no global approval total is assumed.</p>
            <div>
              {cursor ? (
                <Button
                  variant="secondary"
                  onClick={() => setCursor(undefined)}
                >
                  <ArrowLeft size={15} />
                  First task page
                </Button>
              ) : null}
              <Button
                variant="secondary"
                disabled={!data.page.next_cursor}
                onClick={() => setCursor(data.page.next_cursor ?? undefined)}
              >
                Next task page
                <ArrowRight size={15} />
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}
