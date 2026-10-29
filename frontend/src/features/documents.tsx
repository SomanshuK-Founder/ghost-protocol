"use client";
import Link from "next/link";
import { useCallback } from "react";
import { ArrowRight, FileText, RefreshCw, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api/client";
import { documentFields } from "@/lib/evidence";
import { useCursorPage } from "@/lib/use-cursor-page";
import { useResource } from "@/lib/use-resource";
import { EvidenceFields, PageControls } from "@/components/evidence-ui";
import {
  Badge,
  Button,
  EmptyState,
  ErrorPanel,
  LoadingSkeleton,
  Timestamp,
} from "@/components/ui";
import { TechnicalDetails } from "@/components/review-primitives";

export function Documents() {
  const page = useCursorPage();
  const load = useCallback(
    (signal: AbortSignal) =>
      api.get("/api/app/v1/documents", {
        query: { limit: page.limit, cursor: page.cursor },
        signal,
      }),
    [page.limit, page.cursor],
  );
  const { data, error, loading, refresh } = useResource(load);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">OWNER-SCOPED CATALOG</p>
          <h1>Know what’s in scope.</h1>
          <p>
            Authorized catalog metadata. Protected content stays behind the
            gateway.
          </p>
        </div>
        <Button
          variant="secondary"
          disabled={loading}
          onClick={() => {
            page.first();
            refresh();
          }}
        >
          <RefreshCw size={16} />
          Refresh catalog
        </Button>
      </div>
      <div className="mode-strip">
        <span>
          <ShieldCheck size={16} />
          Six-field metadata projection
        </span>
        <span>Synthetic resources only · No document contents</span>
      </div>
      {error ? (
        <ErrorPanel
          error={error}
          onRetry={() => {
            page.first();
            refresh();
          }}
        />
      ) : loading ? (
        <LoadingSkeleton />
      ) : data ? (
        <>
          <div className="document-grid">
            {data.items.length ? (
              data.items.map((document) => (
                <article
                  key={document.resource_id}
                  className="panel document-card"
                >
                  <FileText size={24} className="iris-text" />
                  <Badge value={document.classification} tone="muted" />
                  <h2>{document.display_name}</h2>
                  <p className="catalog-status">
                    <ShieldCheck size={15} />
                    Listed in the active owner catalog
                  </p>
                  <p className="field-help">
                    Metadata availability does not authorize a protected read or
                    sharing.
                  </p>
                  <TechnicalDetails label="Six catalog fields">
                    <EvidenceFields fields={documentFields(document)} />
                  </TechnicalDetails>
                  <Link className="text-link" href="/tasks/new/">
                    Plan a scoped task <ArrowRight size={15} />
                  </Link>
                </article>
              ))
            ) : (
              <section className="panel">
                <EmptyState title="No catalog metadata in this page">
                  The backend has not listed any active synthetic resources for
                  this owner.
                </EmptyState>
              </section>
            )}
          </div>
          <PageControls
            limit={page.limit}
            onLimit={page.changeLimit}
            onFirst={page.first}
            onNext={() => page.next(data.next_cursor)}
            hasNext={Boolean(data.next_cursor)}
            first={!page.cursor}
            label="Documents per page"
          />
          <p className="field-help">
            Catalog snapshot <Timestamp value={data.snapshot_at} />
          </p>
        </>
      ) : null}
    </>
  );
}
