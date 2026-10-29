import Link from "next/link";
export default function Page() {
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">LOCAL OPERATOR GUIDE</p>
          <h1>A private control room.</h1>
          <p>Single process. Literal loopback. Synthetic documents.</p>
        </div>
      </div>
      <section className="panel settings-panel">
        <h2>Start locally</h2>
        <p>
          Follow frontend/README.md in the repository. Build the static UI with
          npm run build, initialize a new disposable ghost-offline-* directory
          with the existing backend bootstrap, then run
          frontend/scripts/serve.py with that directory in a private operator
          terminal.
        </p>
        <p>
          Pairing is disabled unless the operator supplies --pair. The one-use
          code expires after 120 seconds. Use http://127.0.0.1:3000. No
          localhost alias, public tunnel, remote login, real email, or live
          inference is configured.
        </p>
        <h2>When a request is uncertain</h2>
        <p>
          Refresh stored records. A lost response does not prove a command
          failed. Do not create a replacement command or task to repeat an
          uncertain action.
        </p>
        <h2>Human control</h2>
        <p>
          Review the exact requested scope in the approval center. Approve,
          reject, or revoke through a confirmation dialog. Continue an approved
          workflow separately from its task workspace. Continuation stops at
          SAFE_STOPPED and never dispatches a protected operation. Cancel task
          revokes future task authority; it cannot undo an admitted operation.
        </p>
        <h2>Inspect the stored evidence</h2>
        <p>
          Documents lists authorized catalog metadata. Operations separates
          authorization, execution, and external effect for the selected task.
          Audit explorer pages through stored chronological events. Copyable
          references identify records and grant no permission.
        </p>
        <Link href="/settings/" className="text-link">
          Review capability status
        </Link>
      </section>
    </>
  );
}
