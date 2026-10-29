import { Suspense } from "react";
import { OperationDetailPage } from "@/features/operations";
import { LoadingSkeleton } from "@/components/ui";
export default function Page() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <OperationDetailPage />
    </Suspense>
  );
}
