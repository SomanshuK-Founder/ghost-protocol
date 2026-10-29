"use client";
import { useEffect, useId, useState, useRef } from "react";
import type { ReactNode, KeyboardEvent } from "react";
import { Clock3, ShieldCheck } from "lucide-react";
import { Button, Timestamp } from "./ui";

export function trapDialogFocus(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== "Tab") return;
  const controls = [
    ...event.currentTarget.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])',
    ),
  ].filter((element) => element.getClientRects().length > 0);
  const first = controls[0],
    last = controls.at(-1);
  if (!first || !last) {
    event.preventDefault();
    return;
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function TechnicalDetails({
  children,
  label = "Technical metadata",
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <details className="technical-details">
      <summary>{label}</summary>
      <div>{children}</div>
    </details>
  );
}
export function Reference({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd className="mono break">{value ?? "Not recorded"}</dd>
    </div>
  );
}
export function useDeadline(deadline?: string | null) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!deadline) return;
    const tick = () => setNow(Date.now());
    const timer = setTimeout(
      tick,
      Math.max(0, Date.parse(deadline) - Date.now()) + 1,
    );
    const visible = () => {
      if (document.visibilityState === "visible") tick();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [deadline]);
  return { now, expired: Boolean(deadline && now >= Date.parse(deadline)) };
}
export function ApprovalExpiry({
  value,
  state,
}: {
  value: string;
  state?: string;
}) {
  const clock = useDeadline(value);
  const expired = state === "EXPIRED" || clock.expired;
  return (
    <span className={`approval-expiry ${expired ? "danger-text" : ""}`}>
      <Clock3 size={14} aria-hidden="true" />
      <span>
        {expired ? "Review window ended" : "Review deadline"}{" "}
        <Timestamp value={value} />
      </span>
    </span>
  );
}
export function ConfirmDialog({
  open,
  title,
  children,
  pending,
  confirmLabel,
  onConfirm,
  onCancel,
  disabled = false,
  danger = false,
  returnTo,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  pending: boolean;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  disabled?: boolean;
  danger?: boolean;
  returnTo?: HTMLElement | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (open && !dialog.current?.open) {
      dialog.current?.showModal();
      dialog.current
        ?.querySelector<HTMLButtonElement>(".dialog-actions button")
        ?.focus({ preventScroll: true });
    } else if (!open && dialog.current?.open) {
      dialog.current.close();
      const frame = requestAnimationFrame(() => {
        if (returnTo?.isConnected) returnTo.focus();
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [open, returnTo]);
  return (
    <dialog
      ref={dialog}
      className="confirm-dialog review-confirmation"
      aria-labelledby={titleId}
      onKeyDown={trapDialogFocus}
      onCancel={(event) => {
        event.preventDefault();
        if (!pending) onCancel();
      }}
      onClose={() => {
        if (open && !pending) onCancel();
      }}
    >
      <ShieldCheck size={26} className="iris-text" aria-hidden="true" />
      <h2 id={titleId}>{title}</h2>
      <div className="confirmation-content">{children}</div>
      <div className="dialog-actions">
        <Button
          variant="secondary"
          autoFocus
          disabled={pending}
          onClick={onCancel}
        >
          Go back
        </Button>
        <Button
          variant={danger ? "danger" : "primary"}
          disabled={disabled || pending}
          onClick={onConfirm}
        >
          {pending ? "Submitting…" : confirmLabel}
        </Button>
      </div>
      <p className="field-help" role="status">
        {pending
          ? "Waiting for the backend acknowledgment. This command will not retry automatically."
          : "The backend rechecks current authority before accepting this command."}
      </p>
    </dialog>
  );
}
