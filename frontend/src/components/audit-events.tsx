"use client";
import type { TimelineEvent } from "@/lib/api/types";
import { eventFields } from "@/lib/evidence";
import { eventDetail, readable } from "@/lib/presentation";
import { EvidenceFields } from "./evidence-ui";
import { TechnicalDetails } from "./review-primitives";
import { Badge, Timestamp } from "./ui";

export function AuditEvents({ events }: { events: TimelineEvent[] }) {
  return (
    <ol className="audit-list explorer-events">
      {events.map((event) => (
        <li key={event.event_ref}>
          <span className="activity-dot" />
          <div>
            <div className="audit-event-heading">
              <h3>{readable(event.kind)}</h3>
              {event.state || event.decision ? (
                <Badge value={event.state ?? event.decision!} />
              ) : null}
            </div>
            <p>{eventDetail(event)}</p>
            {event.kind === "WORKFLOW_TRANSITION" &&
            event.state === "RESUMED" ? (
              <p className="cyan-text">
                Safe continuation stopped here (SAFE_STOPPED). No protected
                operation was dispatched.
              </p>
            ) : null}
            {event.execution_status === "UNKNOWN" ||
            event.state === "UNKNOWN" ? (
              <p className="notice danger-text">
                Outcome unknown. Reconciliation is required; do not resend.
              </p>
            ) : null}
            <TechnicalDetails label="Event details and references">
              <EvidenceFields fields={eventFields(event)} />
            </TechnicalDetails>
          </div>
          <Timestamp value={event.timestamp} />
        </li>
      ))}
    </ol>
  );
}
