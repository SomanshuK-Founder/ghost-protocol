import { Suspense } from "react";
import { AuditExplorer } from "@/features/audit";
import { LoadingSkeleton } from "@/components/ui";
export default function Page() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <AuditExplorer />
    </Suspense>
  );
}
