"use client";
import { useRef, useState } from "react";
import { api, ApiError } from "@/lib/api/client";
import type { TaskDetail } from "@/lib/api/types";
import { commandBlock, runOwnerCommand } from "@/lib/owner-commands";
import { useSession } from "./session";
import { ConfirmDialog, useDeadline } from "./review-primitives";
import { Button, ErrorPanel } from "./ui";

export function TaskCancel({
  task,
  refreshing,
  onChanged,
}: {
  task: TaskDetail;
  refreshing: boolean;
  onChanged: () => void;
}) {
  const { session, commands } = useSession();
  const [open, setOpen] = useState(false),
    [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const lock = useRef(false);
  const { expired } = useDeadline(task.expires_at);
  async function confirm() {
    if (lock.current) return;
    lock.current = true;
    setPending(true);
    setFailure(null);
    try {
      const fresh = await api.get("/api/app/v1/tasks/{task_ref}", {
        params: { task_ref: task.task_ref },
      });
      if (
        fresh.authority_state !== task.authority_state ||
        fresh.authorization_version !== task.authorization_version ||
        fresh.authority_state !== "OPEN"
      )
        throw new ApiError(409, "REVIEW_CHANGED");
      await runOwnerCommand(commands, {
        kind: "CANCEL",
        taskRef: task.task_ref,
        csrf: session.csrf_token,
      });
    } catch (error) {
      setFailure(error);
    } finally {
      setOpen(false);
      setPending(false);
      lock.current = false;
      onChanged();
    }
  }
  return (
    <section className="task-cancel-panel">
      <div>
        <h2>Task authority</h2>
        <p>
          Cancellation stops future task authority. It cannot undo or guarantee
          interruption of an admitted operation.
        </p>
      </div>
      <Button
        variant="secondary"
        disabled={
          pending ||
          refreshing ||
          expired ||
          task.authority_state !== "OPEN" ||
          Boolean(commandBlock(commands, task.task_ref))
        }
        onClick={(event) => {
          setTrigger(event.currentTarget);
          setOpen(true);
        }}
      >
        Cancel task
      </Button>
      {failure ? <ErrorPanel error={failure} /> : null}
      <ConfirmDialog
        open={open}
        title="Cancel this task?"
        pending={pending}
        confirmLabel="Cancel task"
        danger
        returnTo={trigger}
        onCancel={() => setOpen(false)}
        onConfirm={() => void confirm()}
      >
        <p>
          This revokes future authority for this exact task. Existing approvals
          may be invalidated. An in-flight or UNKNOWN outcome still requires
          inspection and reconciliation; cancellation is not an undo.
        </p>
      </ConfirmDialog>
    </section>
  );
}
