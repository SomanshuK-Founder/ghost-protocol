"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useState } from "react";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { api, ApiError } from "@/lib/api/client";
import { localPage, validTaskRef } from "@/lib/evidence";
import { taskTitle } from "@/lib/presentation";
import { useResource } from "@/lib/use-resource";
import { OperationRecords } from "@/components/operation-records";
import { PageControls } from "@/components/evidence-ui";
import { TaskScopePicker } from "@/components/task-scope-picker";
import {
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
} from "@/components/ui";

export function OperationHistory() {
  const ref = useSearchParams().get("ref") ?? "";
  const router = useRouter();
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">OBSERVE THE OUTCOME</p>
          <h1>Authority isn’t execution.</h1>
          <p>
            Operation state, authorization, and external effect are separate
            facts.
          </p>
        </div>
      </div>
      <TaskScopePicker
        value={ref}
        onChange={(value) =>
          router.replace(
            value
              ? `/operations/?ref=${encodeURIComponent(value)}`
              : "/operations/",
          )
        }
      />
      {ref ? (
        <OperationsForTask key={ref} reference={ref} />
      ) : (
        <section className="panel">
          <EmptyState title="Choose a task to inspect operations">
            Operation history is owner- and task-scoped. No global execution
            totals are assumed.
          </EmptyState>
        </section>
      )}
    </>
  );
}
function OperationsForTask({ reference }: { reference: string }) {
  const [limit, setLimit] = useState(10),
    [index, setIndex] = useState(0);
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (!validTaskRef(reference)) throw new ApiError(404, "NOT_FOUND");
      const params = { task_ref: reference };
      const [task, operations] = await Promise.all([
        api.get("/api/app/v1/tasks/{task_ref}", { params, signal }),
        api.get("/api/app/v1/tasks/{task_ref}/operations", { params, signal }),
      ]);
      return { task, ...operations };
    },
    [reference],
  );
  const { data, loading, error, refresh } = useResource(load);
  const page = localPage(data?.items ?? [], index, limit);
  return (
    <>
      {error ? (
        <ErrorPanel error={error} onRetry={refresh} />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <section className="panel operation-history-panel">
            <div className="section-heading">
              <div>
                <h2>{taskTitle(data.task)}</h2>
                <p className="field-help">
                  {data.items.length} loaded operation records · Up to 20
                  returned by the task endpoint
                </p>
              </div>
              <Button variant="secondary" onClick={refresh}>
                <RefreshCw size={15} />
                Refresh operations
              </Button>
            </div>
            {data.items.length ? (
              <OperationRecords operations={page.items} />
            ) : (
              <EmptyState title="No operation recorded">
                Planning and authorization must produce a genuine record before
                an outcome can be shown.
              </EmptyState>
            )}
          </section>
          <PageControls
            limit={limit}
            onLimit={(value) => {
              setLimit(value);
              setIndex(0);
            }}
            onFirst={() => setIndex(0)}
            onNext={() => setIndex((current) => current + 1)}
            hasNext={page.hasNext}
            first={page.page === 0}
            label="Loaded operations per page"
          />
          <p className="field-help">
            These pages organize the returned set. The verified operation
            endpoint exposes no cursor; browse task pages to inspect another
            task.
          </p>
        </>
      ) : null}
    </>
  );
}
export function OperationDetailPage() {
  const search = useSearchParams();
  const ref = search.get("ref") ?? "",
    operation = search.get("operation") ?? "";
  const load = useCallback(
    async (signal: AbortSignal) => {
      if (
        !validTaskRef(ref) ||
        !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(operation)
      )
        throw new ApiError(404, "NOT_FOUND");
      return api.get(
        "/api/app/v1/tasks/{task_ref}/operations/{operation_ref}",
        { params: { task_ref: ref, operation_ref: operation }, signal },
      );
    },
    [ref, operation],
  );
  const { data, loading, error, refresh } = useResource(load);
  return (
    <>
      <Link
        className="text-link back-link"
        href={`/operations/?ref=${encodeURIComponent(ref)}`}
      >
        <ArrowLeft size={16} />
        Operation history
      </Link>
      <div className="page-heading">
        <div>
          <p className="eyebrow">OWNER-SAFE PROJECTION</p>
          <h1>A record, with provenance.</h1>
          <p>
            No raw tool result, email body, document text, or credential is
            exposed here.
          </p>
        </div>
        <Button variant="secondary" disabled={loading} onClick={refresh}>
          <RefreshCw size={15} />
          Refresh record
        </Button>
      </div>
      {error ? (
        <ErrorPanel error={error} onRetry={refresh} />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <section className="panel operation-history-panel">
          <OperationRecords operations={[data]} detail />
        </section>
      ) : null}
    </>
  );
}
