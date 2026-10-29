"use client";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { Operation } from "@/lib/api/types";
import { needsReconciliation } from "@/lib/evidence";
import { readable } from "@/lib/presentation";
import { EvidenceFields } from "./evidence-ui";
import { TechnicalDetails } from "./review-primitives";
import { Badge, Timestamp } from "./ui";

export function OperationRecords({
  operations,
  detail = false,
}: {
  operations: Operation[];
  detail?: boolean;
}) {
  return (
    <div className="operation-list">
      {operations.map((operation) => (
        <article className="operation-record" key={operation.operation_ref}>
          <div className="operation-top">
            <h3>{operation.action}</h3>
            <Badge value={operation.state} />
          </div>
          <div className="operation-facts">
            <span>
              Authorization<strong>{readable(operation.decision)}</strong>
            </span>
            <span>
              Execution<strong>{readable(operation.execution_status)}</strong>
            </span>
            <span>
              External effect
              <strong>{readable(operation.provenance.effect)}</strong>
            </span>
            <span>
              Evidence<strong>{readable(operation.provenance.evidence)}</strong>
            </span>
          </div>
          <p className="field-help">
            Reason: {readable(operation.reason_code)}
          </p>
          <div className="operation-provenance">
            <Badge value={operation.provenance.environment} tone="muted" />
            <Badge value={operation.provenance.planning_source} tone="iris" />
            {operation.provenance.execution_mode ? (
              <Badge value={operation.provenance.execution_mode} tone="cyan" />
            ) : null}
          </div>
          {needsReconciliation(operation) ? (
            <p className="notice danger-text" role="status">
              Reconciliation required. Do not retry or submit a replacement
              operation.
            </p>
          ) : (
            <p className="field-help">
              A recorded status is not proof of external delivery or protected
              content access. Approval and workflow continuation never dispatch.
            </p>
          )}
          <TechnicalDetails label="Operation metadata and references">
            <EvidenceFields
              fields={[
                {
                  label: "Operation reference",
                  value: operation.operation_ref,
                  copy: true,
                },
                {
                  label: "Task reference",
                  value: operation.task_ref,
                  copy: true,
                },
                {
                  label: "Request ID",
                  value: operation.request_id,
                  copy: true,
                },
                {
                  label: "Audit event reference",
                  value: operation.audit_event_ref,
                  copy: true,
                },
                {
                  label: "Approval reference",
                  value: operation.approval_ref,
                  copy: true,
                },
                { label: "Approval state", value: operation.approval_state },
                {
                  label: "Attempt reference",
                  value: operation.attempt_ref,
                  copy: true,
                },
                { label: "Revision", value: operation.revision },
                { label: "Created", value: operation.created_at },
                { label: "Updated", value: operation.updated_at },
                {
                  label: "Reconciliation required",
                  value: operation.reconciliation_required,
                },
              ]}
            />
          </TechnicalDetails>
          <div className="operation-links">
            {!detail ? (
              <Link
                className="text-link"
                href={`/operations/detail/?ref=${encodeURIComponent(operation.task_ref)}&operation=${encodeURIComponent(operation.operation_ref)}`}
              >
                Inspect operation <ArrowRight size={15} />
              </Link>
            ) : null}
            <Link
              className="text-link"
              href={`/audit/?ref=${encodeURIComponent(operation.task_ref)}`}
            >
              Open task audit <ArrowRight size={15} />
            </Link>
          </div>
          <p className="field-help">
            Updated <Timestamp value={operation.updated_at} />
          </p>
        </article>
      ))}
    </div>
  );
}
