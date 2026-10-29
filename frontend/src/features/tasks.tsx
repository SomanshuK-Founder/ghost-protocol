"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Plus,
  ShieldCheck,
} from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import type { Schema } from "@/lib/api/types";
import { profiles } from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import { useSession } from "@/components/session";
import {
  Button,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";
import { TaskTable } from "@/components/task-table";

export function Tasks() {
  const [cursor, setCursor] = useState<string | undefined>();
  const load = useCallback(
    (signal: AbortSignal) =>
      api.get("/api/app/v1/tasks", { query: { limit: 20, cursor }, signal }),
    [cursor],
  );
  const { data, error, loading, refresh } = useResource(load);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">INTENTIONS, WITH BOUNDARIES</p>
          <h1>Task workspace</h1>
          <p>Every task has a scope. Every next step has a record.</p>
        </div>
        <Link className="button primary" href="/tasks/new/">
          <Plus size={17} />
          Create task
        </Link>
      </div>
      {error ? (
        <ErrorPanel
          error={error}
          onRetry={() => {
            setCursor(undefined);
            refresh();
          }}
        />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <section className="panel">
            <TaskTable tasks={data.items} />
          </section>
          <div className="pagination">
            <span>
              Page snapshot <Timestamp value={data.snapshot_at} />
            </span>
            <div>
              {cursor ? (
                <Button
                  variant="secondary"
                  onClick={() => setCursor(undefined)}
                >
                  <ArrowLeft size={15} />
                  First page
                </Button>
              ) : null}
              <Button
                variant="secondary"
                disabled={!data.next_cursor}
                onClick={() => setCursor(data.next_cursor ?? undefined)}
              >
                Next page
                <ArrowRight size={15} />
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </>
  );
}

export function NewTask() {
  const { session } = useSession();
  const router = useRouter();
  const [profile, setProfile] = useState<Schema["TaskCreate"]["profile_id"]>(
    "document_simulation_v1",
  );
  const [resource, setResource] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  const submitting = useRef(false);
  const uncertain = failure instanceof ApiError && failure.uncertain;
  const load = useCallback(
    (signal: AbortSignal) =>
      api.get("/api/app/v1/documents", {
        query: { limit: 50, cursor },
        signal,
      }),
    [cursor],
  );
  const { data, error, loading, refresh } = useResource(load);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || uncertain) return;
    submitting.current = true;
    setPending(true);
    setFailure(null);
    key.current ??= crypto.randomUUID();
    try {
      const task = await api.post(
        "/api/app/v1/tasks",
        {
          profile_id: profile,
          resource_id: profile === "document_simulation_v1" ? resource : null,
        },
        { csrf: session.csrf_token, key: key.current },
      );
      router.push(`/tasks/detail/?ref=${encodeURIComponent(task.task_ref)}`);
    } catch (e) {
      setFailure(e);
      if (!(e instanceof ApiError && e.uncertain)) key.current = null;
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }
  return (
    <>
      <Link href="/tasks/" className="text-link back-link">
        <ArrowLeft size={16} />
        Task workspace
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">A DELIBERATE FIRST STEP</p>
          <h1>Create an intention.</h1>
          <p>
            Choose a fixed scope. You’ll describe the request before planning.
          </p>
        </div>
      </div>
      <div className="composer-layout">
        <section className="panel composer-panel">
          <form onSubmit={submit}>
            <fieldset disabled={pending || uncertain}>
              <legend>
                01 <span>Choose a task profile</span>
              </legend>
              <div className="profile-choices">
                {Object.entries(profiles).map(([id, option]) => (
                  <label
                    key={id}
                    className={`profile-option ${profile === id ? "selected" : ""}`}
                  >
                    <input
                      type="radio"
                      name="profile"
                      value={id}
                      checked={profile === id}
                      onChange={() => {
                        setProfile(id as typeof profile);
                        key.current = null;
                      }}
                    />
                    <span>
                      <strong>{option.title}</strong>
                      <small>{option.description}</small>
                    </span>
                  </label>
                ))}
              </div>
              {profile === "document_simulation_v1" ? (
                <div className="resource-field">
                  <label htmlFor="resource">
                    02 <span>Select authorized catalog metadata</span>
                  </label>
                  {loading ? (
                    <LoadingSkeleton />
                  ) : error ? (
                    <ErrorPanel error={error} onRetry={refresh} />
                  ) : (
                    <>
                      <select
                        id="resource"
                        value={resource}
                        onChange={(e) => setResource(e.target.value)}
                        required
                        aria-describedby="resource-help"
                      >
                        <option value="">Select a synthetic document</option>
                        {data?.items.map((document) => (
                          <option
                            key={document.resource_id}
                            value={document.resource_id}
                          >
                            {document.display_name} ·{" "}
                            {document.classification
                              .replaceAll("_", " ")
                              .toLowerCase()}
                          </option>
                        ))}
                      </select>
                      <p id="resource-help" className="field-help">
                        Catalog access shows metadata only. Selecting a resource
                        grants no permission to read it.
                      </p>
                      {data?.next_cursor ? (
                        <Button
                          type="button"
                          variant="ghost"
                          onClick={() =>
                            setCursor(data.next_cursor ?? undefined)
                          }
                        >
                          Next catalog page
                        </Button>
                      ) : null}
                    </>
                  )}
                </div>
              ) : null}
            </fieldset>
            {failure ? <ErrorPanel error={failure} /> : null}
            <div className="form-footer">
              <span>
                <ShieldCheck size={15} />
                Creation does not run a model or tool.
              </span>
              <Button
                type="submit"
                disabled={
                  pending ||
                  uncertain ||
                  (profile === "document_simulation_v1" &&
                    (!resource || loading || Boolean(error)))
                }
              >
                {pending ? "Recording task…" : "Create task"}
                <ArrowRight size={16} />
              </Button>
            </div>
            {uncertain ? (
              <Link className="text-link" href="/tasks/">
                Inspect stored tasks before proceeding <ArrowRight size={15} />
              </Link>
            ) : null}
          </form>
        </section>
        <aside className="composer-aside">
          <FileText size={28} />
          <h2>
            A small scope.
            <br />A clear boundary.
          </h2>
          <p>
            The backend fixes the action, purpose, and resource scope for your
            selected profile.
          </p>
          <ol>
            <li>
              <span>01</span>Create a task
            </li>
            <li>
              <span>02</span>Request simulated planning
            </li>
            <li>
              <span>03</span>Inspect the gateway decision
            </li>
          </ol>
          <div className="notice">
            This local demo cannot dispatch protected operations from the
            browser.
          </div>
        </aside>
      </div>
    </>
  );
}
