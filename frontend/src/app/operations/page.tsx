import { Suspense } from "react";
import { OperationHistory } from "@/features/operations";
import { LoadingSkeleton } from "@/components/ui";
export default function Page() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <OperationHistory />
    </Suspense>
  );
}
