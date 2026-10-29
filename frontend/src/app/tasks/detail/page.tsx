import { Suspense } from "react";
import { TaskDetail } from "@/features/task-detail";
import { LoadingSkeleton } from "@/components/ui";
export default function Page() {
  return (
    <Suspense fallback={<LoadingSkeleton />}>
      <TaskDetail />
    </Suspense>
  );
}
