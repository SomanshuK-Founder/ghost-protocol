import { Suspense } from "react";
import { ApprovalDetailPage } from "@/features/approval-detail";
import { LoadingSkeleton } from "@/components/ui";
export default function Page() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <ApprovalDetailPage />
    </Suspense>
  );
}
