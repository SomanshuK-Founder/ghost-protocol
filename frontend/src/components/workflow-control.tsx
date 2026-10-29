"use client";
import { useRef, useState } from "react";
import { ArrowRight, CirclePause, ShieldCheck } from "lucide-react";
import { ApiError } from "@/lib/api/client";
import {
  continuationEligibility,
  continuationSignature,
} from "@/lib/approval-review";
import { commandBlock, runOwnerCommand } from "@/lib/owner-commands";
import { loadEvidence } from "@/lib/task-evidence";
import { readable } from "@/lib/presentation";
import type { Evidence } from "@/lib/presentation";
import { useSession } from "./session";
import {
  ConfirmDialog,
  Reference,
  TechnicalDetails,
  useDeadline,
} from "./review-primitives";
import { Badge, Button, ErrorPanel } from "./ui";

export function WorkflowControl({
  evidence,
  refreshing,
  onChanged,
}: {
  evidence: Evidence;
  refreshing: boolean;
  onChanged: () => void;
}) {
  const { session, commands } = useSession();
  const [confirmation, setConfirmation] = useState<Evidence | null>(null);
  const [busy, setBusy] = useState(false);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [failure, setFailure] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const lock = useRef(false);
  const deadline = [
    evidence.task.expires_at,
    evidence.approval?.expires_at,
    evidence.workflow.expires_at,
  ]
    .filter((v): v is string => Boolean(v))
    .sort((a, b) => Date.parse(a) - Date.parse(b))[0];
  const { expired, now } = useDeadline(deadline);
  const reason = continuationEligibility(evidence, now);
  const blocked = commandBlock(commands, evidence.task.task_ref);
  async function open(target: HTMLElement) {
    if (lock.current || blocked) return;
    setTrigger(target);
    lock.current = true;
    setBusy(true);
    setFailure(null);
    setMessage("");
    try {
      const fresh = await loadEvidence(evidence.task.task_ref);
      if (continuationSignature(fresh) !== continuationSignature(evidence)) {
        onChanged();
        throw new ApiError(409, "REVIEW_CHANGED");
      }
      if (continuationEligibility(fresh, Date.now())) {
        onChanged();
        throw new ApiError(409, "WORKFLOW_NOT_READY");
      }
      setConfirmation(fresh);
    } catch (error) {
      setFailure(error);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  async function confirm() {
    if (!confirmation || lock.current) return;
    lock.current = true;
    setBusy(true);
    setFailure(null);
    try {
      const fresh = await loadEvidence(evidence.task.task_ref);
      if (continuationSignature(fresh) !== continuationSignature(confirmation))
        throw new ApiError(409, "REVIEW_CHANGED");
      if (continuationEligibility(fresh, Date.now()))
        throw new ApiError(409, "WORKFLOW_NOT_READY");
      await runOwnerCommand(commands, {
        kind: "CONTINUE",
        taskRef: evidence.task.task_ref,
        csrf: session.csrf_token,
      });
      setMessage(
        "Continuation acknowledged. Refreshing the stored workflow outcome; no protected dispatch was requested.",
      );
    } catch (error) {
      setFailure(error);
    } finally {
      onChanged();
      setConfirmation(null);
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="panel workflow-panel" id="workflow">
      <div className="section-heading">
        <div>
          <p className="eyebrow">A SEPARATE NEXT STEP</p>
          <h2>Safe continuation</h2>
        </div>
        <Badge
          value={
            evidence.workflow.phase === "RESUMED"
              ? "SAFE_STOPPED"
              : (evidence.workflow.phase ?? "NOT_STARTED")
          }
        />
      </div>
      <p>
        Continue only after an explicit human approval. The backend rechecks
        current authority and resumes the stored workflow to its safe stop.
      </p>
      <div className="workflow-boundary">
        <ShieldCheck size={19} />
        <span>
          Resumed means workflow continuation. It does not mean executed.
        </span>
      </div>
      <p className="action-announcement" role="status" aria-live="polite">
        {message || (busy ? "Checking workflow authority…" : "")}
      </p>
      {failure ? <ErrorPanel error={failure} /> : null}
      {blocked === "UNCERTAIN" ? (
        <p className="notice danger-text" role="alert">
          A command has an uncertain outcome. Reconciliation is required. Do not
          submit a replacement continuation.
        </p>
      ) : null}
      {reason ? (
        <p className="notice">{reason}</p>
      ) : (
        <p className="continuation-ready">
          <ShieldCheck size={16} />
          The backend currently permits a separate continuation request.
        </p>
      )}
      <div className="workflow-actions">
        <Button
          disabled={
            busy || refreshing || Boolean(blocked) || expired || Boolean(reason)
          }
          onClick={(event) => void open(event.currentTarget)}
        >
          <CirclePause size={16} />
          Continue workflow
          <ArrowRight size={16} />
        </Button>
        <span className="field-help">
          {evidence.workflow.phase === "RESUMED"
            ? "No further continuation is available."
            : "No execution endpoint is exposed to the browser."}
        </span>
      </div>
      <TechnicalDetails label="Workflow binding">
        <dl>
          <Reference label="Task" value={evidence.task.task_ref} />
          <Reference label="Binding" value={evidence.workflow.binding_ref} />
          <Reference label="Approval" value={evidence.workflow.approval_ref} />
          <Reference
            label="Operation"
            value={evidence.workflow.operation_ref}
          />
          <Reference label="Backend phase" value={evidence.workflow.phase} />
          <Reference
            label="Authorization version"
            value={evidence.workflow.authorization_version}
          />
          <Reference
            label="Evidence"
            value={readable(evidence.workflow.provenance.evidence)}
          />
        </dl>
      </TechnicalDetails>
      <ConfirmDialog
        returnTo={trigger}
        open={Boolean(confirmation)}
        title="Continue this workflow?"
        pending={busy}
        confirmLabel="Continue workflow"
        disabled={expired || Boolean(blocked)}
        onConfirm={() => void confirm()}
        onCancel={() => setConfirmation(null)}
      >
        <p>
          This requests one bounded continuation of the stored, approved
          workflow. It ends at SAFE_STOPPED. It does not dispatch a protected
          tool, send email, or read document content.
        </p>
        <TechnicalDetails label="Exact continuation binding">
          <dl>
            <Reference label="Task" value={confirmation?.task.task_ref} />
            <Reference
              label="Approval"
              value={confirmation?.workflow.approval_ref}
            />
            <Reference
              label="Operation"
              value={confirmation?.workflow.operation_ref}
            />
            <Reference
              label="Binding"
              value={confirmation?.workflow.binding_ref}
            />
          </dl>
        </TechnicalDetails>
      </ConfirmDialog>
    </section>
  );
}
