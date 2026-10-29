"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CirclePause,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { ApiError } from "@/lib/api/client";
import type { ApprovalDetail } from "@/lib/api/types";
import {
  approvalBound,
  approvalEligibility,
  loadApprovalReview,
  reviewSignature,
} from "@/lib/approval-review";
import type { ApprovalReview } from "@/lib/approval-review";
import { commandBlock, runOwnerCommand } from "@/lib/owner-commands";
import type { CommandKind } from "@/lib/owner-commands";
import { readable, taskTitle } from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import { useSession } from "@/components/session";
import {
  ApprovalExpiry,
  ConfirmDialog,
  Reference,
  TechnicalDetails,
  useDeadline,
} from "@/components/review-primitives";
import { Badge, Button, ErrorPanel, LoadingSkeleton } from "@/components/ui";

type Decision = Exclude<CommandKind, "CONTINUE" | "CANCEL">;
const labels: Record<Decision, string> = {
  APPROVE: "Approve request",
  REJECT: "Reject request",
  REVOKE: "Revoke permission",
};

export function ApprovalScope({
  approval,
  resourceName,
}: {
  approval: ApprovalDetail;
  resourceName?: string;
}) {
  return (
    <div className="approval-scope">
      <dl>
        <div>
          <dt>Requested action</dt>
          <dd>{approval.action}</dd>
        </div>
        <div>
          <dt>Purpose</dt>
          <dd>{readable(approval.purpose)}</dd>
        </div>
      </dl>
      {"resource_id" in approval.arguments ? (
        <div className="review-resource">
          <p className="eyebrow">EXACT RESOURCE</p>
          {resourceName ? (
            <>
              <h3>{resourceName}</h3>
              <TechnicalDetails label="Resource reference">
                <code className="break">{approval.arguments.resource_id}</code>
              </TechnicalDetails>
            </>
          ) : (
            <code className="break">{approval.arguments.resource_id}</code>
          )}
          {approval.resource_versions.map((resource) => (
            <Badge
              key={resource.version_ref}
              value={resource.classification}
              tone="muted"
            />
          ))}
        </div>
      ) : (
        <div className="review-email">
          <dl>
            <div>
              <dt>Recipient</dt>
              <dd className="break">{approval.arguments.recipient}</dd>
            </div>
            <div>
              <dt>Subject</dt>
              <dd className="break">{approval.arguments.subject}</dd>
            </div>
          </dl>
          <h3>Exact email body</h3>
          <pre tabIndex={0} aria-label="Exact synthetic email body">
            {approval.arguments.body}
          </pre>
          <p className="field-help">
            Attachments:{" "}
            {approval.arguments.attachment_resource_ids?.length
              ? approval.arguments.attachment_resource_ids.join(", ")
              : "None"}
          </p>
        </div>
      )}
      <ApprovalExpiry value={approval.expires_at} state={approval.state} />
    </div>
  );
}

export function ApprovalDetailPage() {
  const reference = useSearchParams().get("ref") ?? "";
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(reference))
        throw new ApiError(404, "NOT_FOUND");
      return loadApprovalReview(reference, signal);
    },
    [reference],
  );
  const resource = useResource(load);
  const { session, commands } = useSession();
  const [choice, setChoice] = useState<{
    kind: Decision;
    review: ApprovalReview;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const lock = useRef(false);
  const { expired, now } = useDeadline(resource.data?.approval.expires_at);
  const blocked = resource.data
    ? commandBlock(commands, resource.data.task.task_ref)
    : null;
  async function open(kind: Decision, target: HTMLElement) {
    if (lock.current || !resource.data || blocked) return;
    setTrigger(target);
    lock.current = true;
    setBusy(true);
    setFailure(null);
    setMessage("");
    try {
      const fresh = await loadApprovalReview(reference);
      resource.replace(fresh);
      if (reviewSignature(fresh) !== reviewSignature(resource.data))
        throw new ApiError(409, "REVIEW_CHANGED");
      if (approvalEligibility(fresh, kind, Date.now()))
        throw new ApiError(409, "APPROVAL_STATE_CONFLICT");
      setChoice({ kind, review: fresh });
    } catch (error) {
      setFailure(error);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function confirm() {
    if (!choice || lock.current) return;
    lock.current = true;
    setBusy(true);
    setFailure(null);
    try {
      const fresh = await loadApprovalReview(reference);
      resource.replace(fresh);
      if (reviewSignature(fresh) !== reviewSignature(choice.review))
        throw new ApiError(409, "REVIEW_CHANGED");
      if (approvalEligibility(fresh, choice.kind, Date.now()))
        throw new ApiError(409, "APPROVAL_STATE_CONFLICT");
      await runOwnerCommand(commands, {
        kind: choice.kind,
        taskRef: fresh.task.task_ref,
        approvalRef: reference,
        csrf: session.csrf_token,
      });
      setMessage(
        choice.kind === "APPROVE"
          ? "Approval recorded. This action did not dispatch an operation. Continue separately from the task workspace."
          : choice.kind === "REJECT"
            ? "Rejection recorded. No continuation was requested."
            : "Revocation recorded. This does not undo an already admitted effect.",
      );
      resource.replace(await loadApprovalReview(reference));
    } catch (error) {
      setFailure(error);
      resource.refresh();
    } finally {
      setChoice(null);
      lock.current = false;
      setBusy(false);
    }
  }
  if (resource.error)
    return <ErrorPanel error={resource.error} onRetry={resource.refresh} />;
  if (!resource.data) return <LoadingSkeleton />;
  const { approval, task, operation } = resource.data;
  const unavailable = busy || resource.loading || Boolean(blocked);
  return (
    <>
      <Link className="text-link back-link" href="/approvals/">
        <ArrowLeft size={16} />
        Approval center
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">AN EXACT, HUMAN DECISION</p>
          <h1>Review permission.</h1>
          <p>
            {taskTitle(task)} · {readable(approval.purpose)}
          </p>
        </div>
        <div className="heading-actions">
          <Badge value={approval.state} />
          <Button
            variant="secondary"
            disabled={busy || resource.loading}
            onClick={resource.refresh}
          >
            <RefreshCw size={15} />
            Refresh review
          </Button>
        </div>
      </div>
      <div className="mode-strip">
        <span>
          <ShieldCheck size={16} />
          Owner-scoped review
        </span>
        <span>
          Planning: {readable(approval.provenance.planning_source)} · Effect:{" "}
          {readable(approval.provenance.effect)}
        </span>
      </div>
      <p className="action-announcement" role="status" aria-live="polite">
        {message || (busy ? "Checking current authority. Please wait…" : "")}
      </p>
      {failure ? <ErrorPanel error={failure} /> : null}
      {blocked === "UNCERTAIN" ? (
        <div className="notice danger-text" role="alert">
          An earlier command has an uncertain outcome. Inspect current records;
          do not submit a replacement command in this session.
        </div>
      ) : null}
      {!approvalBound(resource.data) ? (
        <div className="notice danger-text" role="alert">
          Binding not verified. Decisions are disabled.
        </div>
      ) : null}
      <div className="approval-review-layout">
        <section className="panel approval-review-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">REQUESTED SCOPE</p>
              <h2>Only this request.</h2>
            </div>
            <CirclePause size={23} className="amber-text" />
          </div>
          <ApprovalScope
            approval={approval}
            resourceName={resource.data.document?.display_name}
          />
          <TechnicalDetails label="Exact task and operation binding">
            <dl>
              <Reference label="Task" value={approval.task_ref} />
              <Reference label="Operation" value={approval.operation_ref} />
              <Reference label="Request" value={approval.request_id} />
              <Reference label="Approval" value={approval.approval_ref} />
              <Reference
                label="Binding digest"
                value={approval.binding_digest}
              />
              {approval.resource_versions.map((v) => (
                <Reference
                  key={v.version_ref}
                  label="Resource version"
                  value={v.version_ref}
                />
              ))}
              <Reference
                label="Authorization version"
                value={task.authorization_version}
              />
            </dl>
          </TechnicalDetails>
        </section>
        <aside className="panel decision-panel">
          <p className="eyebrow">YOUR AUTHORITY</p>
          <h2>Permission is a boundary.</h2>
          <p>
            Approval is limited to the exact task, action, arguments, resource
            version, and expiry shown here. The gateway retains authority over
            execution.
          </p>
          <dl>
            <div>
              <dt>Operation</dt>
              <dd>
                <Badge value={operation.state} />
              </dd>
            </div>
            <div>
              <dt>Execution</dt>
              <dd>{readable(operation.execution_status)}</dd>
            </div>
            <div>
              <dt>Permission consumed</dt>
              <dd>{approval.consumed ? "Yes" : "No"}</dd>
            </div>
          </dl>
          {expired ? (
            <p className="notice danger-text">
              The review window has ended according to your device clock.
              Refresh for the server’s current state.
            </p>
          ) : null}
          {approval.state === "PENDING" ? (
            <div className="approval-actions">
              <Button
                disabled={
                  unavailable ||
                  expired ||
                  Boolean(approvalEligibility(resource.data, "APPROVE", now))
                }
                onClick={(event) => void open("APPROVE", event.currentTarget)}
              >
                <Check size={17} />
                Approve request
              </Button>
              <Button
                variant="secondary"
                disabled={
                  unavailable ||
                  expired ||
                  Boolean(approvalEligibility(resource.data, "REJECT", now))
                }
                onClick={(event) => void open("REJECT", event.currentTarget)}
              >
                <X size={17} />
                Reject request
              </Button>
            </div>
          ) : (
            <p className="notice">
              {approval.state === "APPROVED"
                ? "Permission is approved. Continue the workflow separately; approval did not execute this request."
                : "This review is closed. It cannot authorize continuation."}
            </p>
          )}
          {["PENDING", "APPROVED"].includes(approval.state) ? (
            <div className="revoke-area">
              <Button
                variant="ghost"
                disabled={
                  unavailable ||
                  expired ||
                  Boolean(approvalEligibility(resource.data, "REVOKE", now))
                }
                onClick={(event) => void open("REVOKE", event.currentTarget)}
              >
                Revoke permission
              </Button>
              <p className="field-help">
                Revocation does not undo or guarantee cancellation of an
                admitted operation.
              </p>
            </div>
          ) : null}
          <Link
            className="text-link"
            href={`/tasks/detail/?ref=${encodeURIComponent(task.task_ref)}#workflow`}
          >
            Open task & continuation <ArrowRight size={16} />
          </Link>
        </aside>
      </div>
      <ConfirmDialog
        returnTo={trigger}
        open={Boolean(choice)}
        title={choice ? `${labels[choice.kind]}?` : "Confirm decision"}
        pending={busy}
        confirmLabel={choice ? labels[choice.kind] : "Confirm"}
        danger={choice?.kind !== "APPROVE"}
        disabled={expired || Boolean(blocked)}
        onConfirm={() => void confirm()}
        onCancel={() => setChoice(null)}
      >
        {choice ? (
          <>
            <p>
              {choice.kind === "APPROVE"
                ? "Record scoped permission only. This does not continue the workflow, read a document, or submit an email."
                : choice.kind === "REJECT"
                  ? "Reject this exact request. Subsequent continuation must be denied."
                  : "Withdraw this permission. An already admitted operation may still be in flight; revocation is not an undo."}
            </p>
            <ApprovalScope
              approval={choice.review.approval}
              resourceName={choice.review.document?.display_name}
            />
            <TechnicalDetails label="Confirmation binding">
              <dl>
                <Reference label="Task" value={choice.review.task.task_ref} />
                <Reference
                  label="Operation"
                  value={choice.review.operation.operation_ref}
                />
                <Reference
                  label="Binding digest"
                  value={choice.review.approval.binding_digest}
                />
              </dl>
            </TechnicalDetails>
          </>
        ) : null}
      </ConfirmDialog>
    </>
  );
}
