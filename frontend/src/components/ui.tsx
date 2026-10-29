"use client";

import {
  AlertTriangle,
  ArrowRight,
  Check,
  Circle,
  Clock3,
  FilePlus2,
  ShieldAlert,
} from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { readable } from "@/lib/presentation";

export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button className={`button ${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}
export function Badge({ value, tone }: { value: string; tone?: string }) {
  const kind =
    tone ??
    (/PENDING|APPROVAL_REQUIRED|AWAITING|PAUSED/.test(value)
      ? "amber"
      : /UNKNOWN|UNCERTAIN|DENIED|DENY|FAILED|REJECTED|REVOKED|EXPIRED|RECONCILIATION/.test(
            value,
          )
        ? "danger"
        : /SAFE_STOPPED|SUCCEEDED|COMPLETED|APPROVED|FINISHED/.test(value)
          ? "success"
          : /RUNNING|PLANNING|CREATED/.test(value)
            ? "iris"
            : "muted");
  const Icon =
    kind === "danger"
      ? AlertTriangle
      : kind === "success"
        ? Check
        : kind === "amber"
          ? Clock3
          : Circle;
  return (
    <span className={`badge ${kind}`}>
      <Icon size={12} aria-hidden="true" />
      {readable(value)}
    </span>
  );
}
export function Timestamp({ value }: { value?: string | null }) {
  if (!value) return <span className="muted">Time not recorded</span>;
  return (
    <time dateTime={value} title={value}>
      {new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(value))}
    </time>
  );
}
export function ErrorPanel({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const code = error instanceof ApiError ? error.code : "REQUEST_FAILED";
  const messages: Record<string, string> = {
    NETWORK_UNAVAILABLE:
      "Connection unavailable. Check the local server, then refresh the recorded state.",
    AUTH_NOT_CONFIGURED:
      "Local pairing is off — enable it through the operator setup.",
    LOGIN_FAILED:
      "This code is invalid, expired, or already used. Request a new code in the private operator terminal.",
    AUTH_RATE_LIMITED:
      "Too many pairing attempts. Wait one minute before trying again.",
    CSRF_INVALID:
      "The session security token is stale. Reload local access before making another change.",
    ORIGIN_FORBIDDEN:
      "This request is outside the configured local origin. Open http://127.0.0.1:3000.",
    NOT_FOUND: "This record is unavailable for the current session.",
    INVALID_CURSOR:
      "This list snapshot expired. Refresh the list from the first page.",
    INVALID_REQUEST: "Check the form fields and the selected task profile.",
    REVIEW_CHANGED:
      "This review changed. Read the refreshed scope and status before deciding again.",
    APPROVAL_STATE_CONFLICT:
      "This approval expired or changed. Refresh and inspect its current state.",
    WORKFLOW_NOT_READY:
      "The workflow is not available for continuation. Inspect the current approval and task state.",
    WORKFLOW_DENIED:
      "Continuation is denied by the current authority. Inspect the approval record.",
    RECONCILIATION_REQUIRED:
      "The operation requires reconciliation. Do not retry or submit a replacement command.",
    COMMAND_UNCERTAIN:
      "An earlier command has an uncertain outcome. Inspect the stored records before any further action.",
    COMMAND_IN_PROGRESS:
      "A command is already pending. Wait for its acknowledgment and inspect the recorded outcome.",
    TASK_NOT_ACTIVE:
      "This task is no longer active. No continuation can be requested.",
  };
  return (
    <div className="error-panel" role="alert">
      <ShieldAlert size={20} aria-hidden="true" />
      <div>
        <strong>
          {messages[code] ??
            "The request could not be completed. Refresh the recorded state before taking further action."}
        </strong>
        <p className="mono">{readable(code)}</p>
        {error instanceof ApiError && error.uncertain ? (
          <p>
            The command may have committed. Reconciliation is required; do not
            submit a replacement command.
          </p>
        ) : null}
        {error instanceof ApiError && error.correlation ? (
          <p className="mono break">Reference: {error.correlation}</p>
        ) : null}
        {onRetry ? (
          <Button variant="secondary" onClick={onRetry}>
            Refresh state <ArrowRight size={14} />
          </Button>
        ) : null}
      </div>
    </div>
  );
}
export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <FilePlus2 size={28} aria-hidden="true" />
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
export function LoadingSkeleton() {
  return (
    <div className="skeleton" role="status" aria-label="Loading local records">
      <span />
      <span />
      <span />
      <p>Loading local records…</p>
    </div>
  );
}
