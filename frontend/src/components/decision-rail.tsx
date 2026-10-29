"use client";
import { useRef, useState } from "react";
import {
  Check,
  Circle,
  CirclePause,
  OctagonX,
  TriangleAlert,
  X,
} from "lucide-react";
import { decisionNodes } from "@/lib/presentation";
import type { Evidence, RailState } from "@/lib/presentation";
import { Timestamp, Button } from "./ui";
import { currentRailStage, railRecord } from "@/lib/rail-records";
import { readable } from "@/lib/presentation";
import { trapDialogFocus } from "./review-primitives";

const icons: Record<RailState, typeof Check> = {
  complete: Check,
  active: Circle,
  blocked: CirclePause,
  denied: OctagonX,
  uncertain: TriangleAlert,
  unverified: Circle,
};
export function DecisionRail({ evidence }: { evidence: Evidence }) {
  const nodes = decisionNodes(evidence);
  const current = currentRailStage(evidence);
  const [selected, setSelected] = useState<number | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  const record = selected === null ? null : railRecord(evidence, selected);
  return (
    <section className="decision-section" aria-labelledby="rail-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">THE DECISION RAIL</p>
          <h2 id="rail-title">From intention to evidence.</h2>
        </div>
        <span className="trace-label">BACKEND RECORDS</span>
      </div>
      <ol className="decision-rail">
        {nodes.map((node, index) => {
          const Icon = icons[node.state];
          return (
            <li
              key={node.title}
              className={`rail-node ${node.state} ${current === index ? "current-stage" : ""}`}
              aria-current={current === index ? "step" : undefined}
            >
              <div className="rail-track">
                <span className="rail-dot">
                  <Icon size={17} aria-hidden="true" />
                </span>
                <span className="rail-index">0{index + 1}</span>
              </div>
              <h3>{node.title}</h3>
              <strong>{node.label}</strong>
              <p>{node.detail}</p>
              <small>
                {node.timestamp ? (
                  <Timestamp value={node.timestamp} />
                ) : (
                  "No timestamp recorded"
                )}
              </small>
              {railRecord(evidence, index) ? (
                <Button
                  variant="ghost"
                  className="rail-ref"
                  aria-label={`Inspect ${node.title.toLowerCase()} record`}
                  onClick={(event) => {
                    trigger.current = event.currentTarget;
                    setSelected(index);
                    dialog.current?.showModal();
                  }}
                >
                  Inspect record
                </Button>
              ) : null}
              <span className="sr-only">{node.state}</span>
            </li>
          );
        })}
      </ol>
      <div className="rail-footnote">
        <CirclePause size={15} />
        <span>
          Authorization and execution are separate. Approval alone never
          dispatches an operation.
        </span>
      </div>
      <dialog
        ref={dialog}
        className="record-dialog"
        aria-labelledby="record-title"
        onKeyDown={trapDialogFocus}
        onClose={() => trigger.current?.focus({ preventScroll: true })}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">STORED RECORD · READ ONLY</p>
            <h2 id="record-title">
              {selected === null ? "Record" : nodes[selected].title}
            </h2>
          </div>
          <Button
            variant="ghost"
            aria-label="Close record"
            onClick={() => dialog.current?.close()}
          >
            <X size={20} />
          </Button>
        </div>
        <p className="field-help">
          This is the owner-safe backend snapshot already loaded in this view.
          Refresh records to inspect later changes.
        </p>
        {record ? (
          <dl className="record-fields">
            {Object.entries(record).map(([name, value]) => (
              <div key={name}>
                <dt>{readable(name)}</dt>
                <dd className="mono break">
                  {value === null || value === undefined
                    ? "Not recorded"
                    : typeof value === "object"
                      ? JSON.stringify(value, null, 2)
                      : String(value)}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p>No record is available in this snapshot.</p>
        )}
      </dialog>
    </section>
  );
}
