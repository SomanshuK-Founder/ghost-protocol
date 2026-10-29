"use client";
import { useId, useState } from "react";
import { ArrowLeft, ArrowRight, Check, Copy } from "lucide-react";
import type { Field } from "@/lib/evidence";
import { Button } from "./ui";

export function CopyReference({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  const [message, setMessage] = useState("");
  async function copy() {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setMessage("Reference copied");
    } catch {
      setMessage(
        "Clipboard unavailable. Select the reference text to copy manually.",
      );
    }
  }
  return (
    <span
      className={`copy-reference ${message && message !== "Reference copied" ? "copy-failed" : ""}`}
    >
      <Button
        variant="ghost"
        type="button"
        aria-label={`Copy ${label.toLowerCase()}`}
        onClick={() => void copy()}
      >
        {message === "Reference copied" ? (
          <Check size={15} />
        ) : (
          <Copy size={15} />
        )}
      </Button>
      <span
        role="status"
        className={message === "Reference copied" ? "sr-only" : "field-help"}
      >
        {message}
      </span>
    </span>
  );
}
export function EvidenceFields({ fields }: { fields: Field[] }) {
  return (
    <dl className="evidence-fields">
      {fields.map(({ label, value, copy }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            <code className="mono break">
              {value === null || value === undefined
                ? "Not recorded"
                : String(value)}
            </code>
            {copy && typeof value === "string" ? (
              <CopyReference value={value} label={label} />
            ) : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function PageControls({
  limit,
  onLimit,
  onFirst,
  onNext,
  hasNext,
  first,
  label = "Records per page",
  pending = false,
}: {
  limit: number;
  onLimit: (value: number) => void;
  onFirst: () => void;
  onNext: () => void;
  hasNext: boolean;
  first: boolean;
  label?: string;
  pending?: boolean;
}) {
  const id = useId();
  return (
    <div className="page-controls">
      <div>
        <label htmlFor={id}>{label}</label>
        <select
          id={id}
          value={limit}
          disabled={pending}
          onChange={(event) => onLimit(Number(event.target.value))}
        >
          {[1, 5, 10, 20, 50].map((count) => (
            <option key={count} value={count}>
              {count}
            </option>
          ))}
        </select>
      </div>
      <div className="page-control-actions">
        <Button
          variant="secondary"
          disabled={first || pending}
          onClick={onFirst}
        >
          <ArrowLeft size={15} />
          First page
        </Button>
        <Button
          variant="secondary"
          disabled={!hasNext || pending}
          onClick={onNext}
        >
          Next page
          <ArrowRight size={15} />
        </Button>
      </div>
    </div>
  );
}
