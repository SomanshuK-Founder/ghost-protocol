"use client";
import Link from "next/link";
import { useCallback } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  CirclePause,
  Clock3,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { api } from "@/lib/api/client";
import { loadEvidence } from "@/lib/task-evidence";
import {
  eventDetail,
  readable,
  taskState,
  taskTitle,
} from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import {
  Badge,
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";
import { DecisionRail } from "@/components/decision-rail";
import { TaskTable } from "@/components/task-table";

export function Dashboard() {
  const load = useCallback(async (signal: AbortSignal) => {
    const page = await api.get("/api/app/v1/tasks", {
      query: { limit: 8 },
      signal,
    });
    const [focus, queues] = await Promise.all([
      page.items[0] ? loadEvidence(page.items[0].task_ref, signal) : null,
      Promise.all(
        page.items
          .filter((t) => t.approval_ref)
          .map((t) =>
            api.get("/api/app/v1/approvals", {
              query: { task_ref: t.task_ref },
              signal,
            }),
          ),
      ),
    ]);
    return { page, focus, approvals: queues.flatMap((q) => q.items) };
  }, []);
  const { data, loading, error, refresh } = useResource(load);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">YOUR PERSONAL AI CONTROL ROOM</p>
          <h1>
            Your agent.
            <br className="mobile-only" /> Your call.
          </h1>
          <p>A clear view of every intention, decision, and boundary.</p>
        </div>
        <Link className="button primary" href="/tasks/new/">
          <Plus size={17} />
          Create task
        </Link>
      </div>
      <div className="mode-strip">
        <span>
          <ShieldCheck size={16} />
          Local offline workspace
        </span>
        <span>
          Simulated planning <span className="strip-divider">/</span> No browser
          dispatch
        </span>
      </div>
      {error ? (
        <ErrorPanel error={error} onRetry={refresh} />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <div className="dashboard-grid">
            <section className="focus-panel">
              <div className="section-heading">
                <p className="eyebrow">IN FOCUS</p>
                <span className="mono">LATEST TASK</span>
              </div>
              {data.focus ? (
                <>
                  <div className="focus-title">
                    <span className="focus-number">01</span>
                    <div>
                      <Badge value={taskState(data.focus.task)} />
                      <h2>{taskTitle(data.focus.task)}</h2>
                      <p>{readable(data.focus.task.purpose)}</p>
                    </div>
                  </div>
                  <div className="focus-meta">
                    <span>
                      Planning source
                      <strong>
                        {readable(
                          data.focus.planning.provenance.planning_source,
                        )}
                      </strong>
                    </span>
                    <span>
                      External effect
                      <strong>
                        {readable(data.focus.task.provenance.effect)}
                      </strong>
                    </span>
                  </div>
                  <Link
                    className="text-link"
                    href={`/tasks/detail/?ref=${data.focus.task.task_ref}`}
                  >
                    Open task workspace <ArrowRight size={17} />
                  </Link>
                </>
              ) : (
                <div className="focus-empty">
                  <CirclePause size={30} />
                  <h2>Ready for your first intention.</h2>
                  <p>
                    Create a task to begin a traceable, owner-scoped workflow.
                  </p>
                  <Link className="text-link" href="/tasks/new/">
                    Choose a task <ArrowRight size={17} />
                  </Link>
                </div>
              )}
            </section>
            <section className="review-panel" id="pending-review">
              <div className="section-heading">
                <p className="eyebrow">HUMAN CHECKPOINT</p>
                <Clock3 size={18} />
              </div>
              <div className="review-count">
                <strong>{data.approvals.length}</strong>
                <span>
                  awaiting
                  <br />
                  your review
                </span>
              </div>
              <p>
                Pending approvals in the {data.page.items.length} loaded tasks.
                Human decisions are separate from execution.
              </p>
              {data.approvals[0] ? (
                <Link
                  className="button secondary"
                  href={`/approvals/detail/?ref=${encodeURIComponent(data.approvals[0].approval_ref)}`}
                >
                  Inspect pending request <ArrowUpRight size={16} />
                </Link>
              ) : (
                <span className="quiet-status">
                  <ShieldCheck size={16} />
                  No pending requests in this page
                </span>
              )}
              <Link className="text-link" href="/approvals/">
                Open approval center <ArrowRight size={15} />
              </Link>
            </section>
          </div>
          {data.focus ? <DecisionRail evidence={data.focus} /> : null}
          <div className="section-heading task-list-heading">
            <div>
              <p className="eyebrow">THE WORKSPACE</p>
              <h2>Recent tasks</h2>
            </div>
            <Link className="text-link" href="/tasks/">
              All tasks <ArrowRight size={16} />
            </Link>
          </div>
          <section className="panel">
            <TaskTable tasks={data.page.items} />
          </section>
          <div className="lower-grid">
            <section className="panel activity-panel">
              <div className="section-heading">
                <h2>Recent activity</h2>
                <span className="trace-label">FOCUSED TASK · LOADED PAGE</span>
              </div>
              {data.focus?.timeline.length ? (
                <ol className="activity-list">
                  {data.focus.timeline
                    .filter((event) => event.kind !== "APPROVAL_VIEWED")
                    .slice(-4)
                    .reverse()
                    .map((event) => (
                      <li key={event.event_ref}>
                        <span className="activity-dot" />
                        <div>
                          <strong>{readable(event.kind)}</strong>
                          <span>{eventDetail(event)}</span>
                        </div>
                        <Timestamp value={event.timestamp} />
                      </li>
                    ))}
                </ol>
              ) : (
                <EmptyState title="The record starts with a decision">
                  Planning and authorization records will appear here when the
                  backend records them.
                </EmptyState>
              )}
              {data.focus ? (
                <Link
                  className="text-link"
                  href={`/audit/?ref=${encodeURIComponent(data.focus.task.task_ref)}`}
                >
                  Open audit explorer <ArrowUpRight size={15} />
                </Link>
              ) : null}
            </section>
            <section className="capability-panel">
              <ShieldCheck size={23} />
              <h2>
                Boundaries are part
                <br />
                of the product.
              </h2>
              <p>
                Task planning and owner-scoped audit records are available
                locally. Native sandbox enforcement and live model inference
                through this app are not verified.
              </p>
              <Link className="text-link" href="/settings/">
                Inspect capability status <ArrowUpRight size={16} />
              </Link>
            </section>
          </div>
          <div className="snapshot-note">
            <Timestamp value={data.page.snapshot_at} />
            <span>
              Page snapshot ·{" "}
              <Button variant="ghost" onClick={refresh}>
                Refresh records
              </Button>
            </span>
          </div>
        </>
      ) : null}
    </>
  );
}
