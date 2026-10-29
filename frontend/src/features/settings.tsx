"use client";
import { useCallback, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { useSession } from "@/components/session";
import {
  Badge,
  Button,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";
import { ConfirmDialog } from "@/components/review-primitives";
import { useResource } from "@/lib/use-resource";

export function Settings() {
  const { session, inspectSession, logout } = useSession();
  const [logoutOpen, setLogoutOpen] = useState(false),
    [leaving, setLeaving] = useState(false);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const load = useCallback(
    () =>
      inspectSession().then((view) => ({
        authenticated: view.authenticated,
        checkedAt: new Date().toISOString(),
      })),
    [inspectSession],
  );
  const connection = useResource(load);
  const capabilities = [
    [
      "Application API",
      "LOCAL OFFLINE",
      "Accepted ghost-app-v1. Durable tasks, approvals, revocation, separate continuation, cancellation, catalog metadata, operation history, and cursor-paginated audit events.",
    ],
    [
      "Planning",
      "SIMULATED",
      "Deterministic mock model through the existing LangGraph planning host.",
    ],
    [
      "Protected execution from browser",
      "UNAVAILABLE",
      "No browser dispatch endpoint. Approval and continuation do not send email or read a document.",
    ],
    [
      "Native OpenShell enforcement",
      "NOT VERIFIED",
      "Native admission, full isolation, and runtime enforcement remain unverified.",
    ],
    [
      "Live inference through this app",
      "NOT VERIFIED",
      "Earlier isolated Nemotron via Nebius probes are separate historical evidence.",
    ],
    [
      "Public email / deployed HTTPS / production MySQL",
      "NOT VERIFIED",
      "This build is a literal-loopback, single-process SQLite demonstration.",
    ],
  ];
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">KNOW THE BOUNDARY</p>
          <h1>Clarity is a capability.</h1>
          <p>
            What this workspace supports, and what the evidence can tell you.
          </p>
        </div>
        <ShieldCheck size={32} className="iris-text" />
      </div>
      <section
        className="panel settings-panel connection-panel"
        aria-labelledby="connection-title"
      >
        <div className="section-heading">
          <h2 id="connection-title">Backend connection</h2>
          <Button
            variant="secondary"
            disabled={connection.loading}
            onClick={connection.refresh}
          >
            <RefreshCw size={15} />
            Check connection
          </Button>
        </div>
        {connection.error ? (
          <ErrorPanel error={connection.error} onRetry={connection.refresh} />
        ) : connection.loading ? (
          <LoadingSkeleton />
        ) : connection.data ? (
          <>
            <p className="connection-verified">
              <ShieldCheck size={18} />
              The local session endpoint responded.
            </p>
            <p>
              Same-origin authenticated session check ·{" "}
              <Timestamp value={connection.data.checkedAt} />
            </p>
            <p className="field-help">
              Check time is measured on this device. This is a point-in-time API
              response, not continuous monitoring or a claim about live
              inference or sandbox enforcement.
            </p>
          </>
        ) : null}
      </section>
      <section className="panel settings-panel">
        <h2>Local session</h2>
        <dl>
          <div>
            <dt>Mode</dt>
            <dd>{session.mode}</dd>
          </div>
          <div>
            <dt>Owner</dt>
            <dd>{session.owner?.display_name}</dd>
          </div>
          <div>
            <dt>Idle expiry at last session check</dt>
            <dd>
              <Timestamp value={session.idle_expires_at} />
            </dd>
          </div>
          <div>
            <dt>Absolute expiry</dt>
            <dd>
              <Timestamp value={session.absolute_expires_at} />
            </dd>
          </div>
        </dl>
        <p className="field-help">
          HttpOnly, SameSite=Strict cookie. CSRF stays in memory. Restarting the
          server invalidates sessions.
        </p>
        <Button
          variant="secondary"
          onClick={(event) => {
            setTrigger(event.currentTarget);
            setLogoutOpen(true);
          }}
        >
          End local session
        </Button>
      </section>
      <ConfirmDialog
        open={logoutOpen}
        title="End the local session?"
        pending={leaving}
        confirmLabel="Log out"
        returnTo={trigger}
        onCancel={() => setLogoutOpen(false)}
        onConfirm={() => {
          setLeaving(true);
          void logout();
        }}
      >
        <p>
          Local drafts and client command memory will be cleared. Stored tasks
          and consent remain on the server. Logout does not revoke permission or
          undo admitted work.
        </p>
      </ConfirmDialog>
      <section className="panel settings-panel">
        <h2>Capability status</h2>
        <div className="capability-list">
          {capabilities.map(([name, status, description]) => (
            <div key={name}>
              <div>
                <h3>{name}</h3>
                <p>{description}</p>
              </div>
              <Badge
                value={status}
                tone={
                  status === "LOCAL OFFLINE"
                    ? "cyan"
                    : status === "SIMULATED"
                      ? "iris"
                      : "muted"
                }
              />
            </div>
          ))}
        </div>
      </section>
      <section className="panel settings-panel">
        <h2>Read the provenance</h2>
        <p>
          Configured is a selected profile. Observed is recorded evidence.
          Unattested and unconfirmed mean an effect has not been established by
          the application. A stored operation state alone is not confirmed
          delivery.
        </p>
        <div className="provenance-legend">
          <Badge value="MOCK_MODEL" tone="iris" />
          <Badge value="SIMULATED" tone="cyan" />
          <Badge value="UNATTESTED" tone="amber" />
          <Badge value="UNCONFIRMED" tone="amber" />
          <Badge value="UNKNOWN" tone="danger" />
        </div>
        <p>
          SAFE_STOPPED corresponds to a completed continuation with backend
          workflow phase RESUMED. It does not mean a protected operation was
          dispatched.
        </p>
        <a className="text-link" href="/help/">
          Local setup & help
        </a>
      </section>
    </>
  );
}
