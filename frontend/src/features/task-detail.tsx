"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  CirclePause,
  FileCheck2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { loadEvidence } from "@/lib/task-evidence";
import { readable, taskState, taskTitle } from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import { useSession } from "@/components/session";
import { DecisionRail } from "@/components/decision-rail";
import { WorkflowControl } from "@/components/workflow-control";
import { OperationRecords } from "@/components/operation-records";
import { AuditEvents } from "@/components/audit-events";
import { TaskCancel } from "@/components/task-cancel";
import {
  ApprovalExpiry,
  TechnicalDetails,
} from "@/components/review-primitives";
import {
  Badge,
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";

export function TaskDetail() {
  const taskRef = useSearchParams().get("ref") ?? "";
  const validRef = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(taskRef);
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!validRef) throw new ApiError(404, "NOT_FOUND");
      return loadEvidence(taskRef, signal);
    },
    [taskRef, validRef],
  );
  const { data, loading, error, refresh } = useResource(load);
  const { session } = useSession();
  const [request, setRequest] = useState("");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  const submitting = useRef(false);
  const polls = useRef(0);
  useEffect(() => {
    if (
      !data ||
      data.planning.state !== "RUNNING" ||
      polls.current >= 8 ||
      error
    )
      return;
    const timer = setTimeout(() => {
      polls.current += 1;
      refresh();
    }, 2500);
    return () => clearTimeout(timer);
  }, [data, error, refresh]);
  async function plan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !request.trim()) return;
    submitting.current = true;
    setPending(true);
    setFailure(null);
    key.current ??= crypto.randomUUID();
    try {
      await api.post(
        "/api/app/v1/tasks/{task_ref}/planning",
        { user_request: request.trim() },
        {
          params: { task_ref: taskRef },
          csrf: session.csrf_token,
          key: key.current,
        },
      );
      setRequest("");
      refresh();
    } catch (e) {
      setFailure(e);
      refresh();
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }
  if (error) return <ErrorPanel error={error} onRetry={refresh} />;
  if (!data) return <LoadingSkeleton />;
  const blocked =
    pending ||
    loading ||
    data.planning.state !== "NOT_STARTED" ||
    data.task.authority_state !== "OPEN" ||
    data.task.in_flight ||
    data.task.reconciliation_required ||
    (failure instanceof ApiError && failure.uncertain);
  return (
    <>
      <Link className="text-link back-link" href="/tasks/">
        <ArrowLeft size={16} />
        Task workspace
      </Link>
      <div className="page-heading detail-heading">
        <div>
          <p className="eyebrow">INTENTION / {data.task.allowed_action}</p>
          <h1>{taskTitle(data.task)}</h1>
          <TechnicalDetails label="Task reference">
            <code className="mono break">{taskRef}</code>
          </TechnicalDetails>
        </div>
        <div className="heading-actions">
          <Badge value={taskState(data.task)} />
          <Button variant="secondary" onClick={refresh} disabled={loading}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        </div>
      </div>
      <div className="mode-strip">
        <span>
          <Sparkles size={15} />
          {data.planning.provenance.planning_source === "MOCK_MODEL"
            ? "Simulated planning · mock model"
            : `Planning source: ${readable(data.planning.provenance.planning_source)}`}
        </span>
        <span>
          Effect: {readable(data.task.provenance.effect)}{" "}
          <span className="strip-divider">/</span> Evidence:{" "}
          {readable(data.task.provenance.evidence)}
        </span>
      </div>
      <DecisionRail evidence={data} />
      <div className="detail-grid">
        <section className="panel planning-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">THE AGENT PROPOSES</p>
              <h2>Planning workspace</h2>
            </div>
            <Badge value={data.planning.state} />
          </div>
          <p>
            Describe your request within this task’s fixed scope. Planning
            proposes intentions and requests authorization; it cannot execute a
            protected action.
          </p>
          {failure ? <ErrorPanel error={failure} /> : null}
          {data.planning.state === "NOT_STARTED" ? (
            <form onSubmit={plan}>
              <label htmlFor="planning-request">Your request</label>
              <textarea
                id="planning-request"
                value={request}
                onChange={(e) => setRequest(e.target.value)}
                required
                minLength={1}
                maxLength={4000}
                rows={4}
                disabled={blocked}
                placeholder={
                  data.task.profile_id === "document_simulation_v1"
                    ? "Summarize this synthetic document, but never share the original."
                    : "Prepare an email using this task’s approved synthetic template."
                }
                aria-describedby="planning-help"
              />
              <div className="textarea-footer">
                <span id="planning-help">
                  {request.length}/4000 · kept in memory
                </span>
                <Button type="submit" disabled={blocked || !request.trim()}>
                  <Sparkles size={15} />
                  {pending
                    ? "Planning… bounded to 18 seconds"
                    : "Start simulated planning"}
                </Button>
              </div>
            </form>
          ) : (
            <div className="plan-record">
              <dl>
                <div>
                  <dt>Outcome</dt>
                  <dd>{readable(data.planning.outcome)}</dd>
                </div>
                <div>
                  <dt>Intent</dt>
                  <dd>{readable(data.planning.intent)}</dd>
                </div>
                <div>
                  <dt>Proposed actions</dt>
                  <dd>
                    {data.planning.proposed_actions.join(", ") ||
                      "None recorded"}
                  </dd>
                </div>
                <div>
                  <dt>Gateway decision</dt>
                  <dd>{readable(data.planning.authorization_decision)}</dd>
                </div>
                <div>
                  <dt>Reason</dt>
                  <dd>
                    {readable(
                      data.planning.reason_code ?? data.planning.error_code,
                    )}
                  </dd>
                </div>
              </dl>
              {data.planning.state === "RUNNING" ? (
                <p role="status">
                  Reading stored status at bounded intervals. Refresh manually
                  if it remains active.
                </p>
              ) : null}
            </div>
          )}
        </section>
        <section className="panel authority-panel" id="approval">
          <div className="section-heading">
            <div>
              <p className="eyebrow">YOU RETAIN AUTHORITY</p>
              <h2>Human checkpoint</h2>
            </div>
            <CirclePause size={22} className="amber-text" />
          </div>
          {data.approval ? (
            <>
              <Badge value={data.approval.state} />
              <dl>
                <div>
                  <dt>Workflow</dt>
                  <dd>
                    {data.workflow.phase === "RESUMED"
                      ? "SAFE_STOPPED (RESUMED)"
                      : readable(data.workflow.phase)}
                  </dd>
                </div>
              </dl>
              <ApprovalExpiry
                value={data.approval.expires_at}
                state={data.approval.state}
              />
              <p className="notice">
                {data.approval.state === "PENDING"
                  ? "A human decision is required. Inspect the exact task, action, resource, and expiry before approving or rejecting."
                  : "This stored decision is not proof of execution. Continuation remains a separate explicit action."}
              </p>
              <Link
                className="button secondary"
                href={`/approvals/detail/?ref=${encodeURIComponent(data.approval.approval_ref)}`}
              >
                Review permission <ArrowUpRight size={16} />
              </Link>
            </>
          ) : (
            <EmptyState title="No approval recorded">
              A pending review appears here only when the gateway requests it.
            </EmptyState>
          )}
          <div className="boundary-line">
            <ShieldCheck size={17} />
            <span>Approval never triggers automatic execution.</span>
          </div>
        </section>
      </div>
      <WorkflowControl
        evidence={data}
        refreshing={loading}
        onChanged={refresh}
      />
      <section className="panel evidence-panel" id="evidence">
        <div className="section-heading">
          <div>
            <p className="eyebrow">THE EVIDENCE</p>
            <h2>Operation records</h2>
          </div>
          <FileCheck2 size={21} className="cyan-text" />
        </div>
        {data.operations.length ? (
          <OperationRecords operations={data.operations} />
        ) : (
          <EmptyState title="No operation recorded">
            Authorization and operation evidence will appear after planning. No
            success is assumed.
          </EmptyState>
        )}
      </section>
      <section className="panel timeline-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">DURABLE HISTORY</p>
            <h2>Audit lens</h2>
          </div>
          <span className="trace-label">FIRST 5 LOADED EVENTS</span>
        </div>
        {data.timeline.length ? (
          <AuditEvents events={data.timeline.slice(0, 5)} />
        ) : (
          <EmptyState title="No audit events yet">
            This timeline contains only stored, owner-scoped backend records.
          </EmptyState>
        )}
        <Link
          href={`/audit/?ref=${encodeURIComponent(taskRef)}`}
          className="text-link"
        >
          Explore all audit pages <ArrowUpRight size={15} />
        </Link>
      </section>
      <div className="evidence-navigation">
        <Link
          className="text-link"
          href={`/operations/?ref=${encodeURIComponent(taskRef)}`}
        >
          Open operation history <ArrowUpRight size={15} />
        </Link>
        <Link
          className="text-link"
          href={`/audit/?ref=${encodeURIComponent(taskRef)}`}
        >
          Open audit explorer <ArrowUpRight size={15} />
        </Link>
      </div>
      <TaskCancel task={data.task} refreshing={loading} onChanged={refresh} />
      <p className="field-help">
        Created <Timestamp value={data.task.created_at} /> · Task expires{" "}
        <Timestamp value={data.task.expires_at} /> · Authorization version{" "}
        {data.task.authorization_version}
      </p>
    </>
  );
}
