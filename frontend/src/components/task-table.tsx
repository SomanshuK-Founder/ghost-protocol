"use client";
import Link from "next/link";
import { ArrowUpRight, FileText, Mail } from "lucide-react";
import type { Task } from "@/lib/api/types";
import { taskState, taskTitle } from "@/lib/presentation";
import { Badge, EmptyState, Timestamp } from "./ui";
import { TechnicalDetails } from "./review-primitives";

export function TaskTable({ tasks }: { tasks: Task[] }) {
  if (!tasks.length)
    return (
      <EmptyState
        title="Your next intention starts here"
        action={
          <Link className="button primary" href="/tasks/new/">
            Create your first task <ArrowUpRight size={16} />
          </Link>
        }
      >
        Choose a scoped task. Review its plan before any further decision.
      </EmptyState>
    );
  return (
    <div className="table-wrap">
      <table className="task-table">
        <caption className="sr-only">
          Owner-scoped tasks in the current page
        </caption>
        <thead>
          <tr>
            <th>Task / profile</th>
            <th>Status</th>
            <th>Created</th>
            <th>
              <span className="sr-only">Open task</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr key={task.task_ref}>
              <td>
                <Link
                  className="task-name"
                  href={`/tasks/detail/?ref=${encodeURIComponent(task.task_ref)}`}
                >
                  <span className="task-icon">
                    {task.profile_id === "document_simulation_v1" ? (
                      <FileText size={19} />
                    ) : (
                      <Mail size={19} />
                    )}
                  </span>
                  <span>
                    <strong>{taskTitle(task)}</strong>
                    <small>
                      {task.profile_id === "document_simulation_v1"
                        ? "Synthetic document scope"
                        : "Fixed synthetic email scope"}
                    </small>
                  </span>
                </Link>
                <TechnicalDetails label="Task reference">
                  <code className="mono break">{task.task_ref}</code>
                </TechnicalDetails>
              </td>
              <td>
                <Badge value={taskState(task)} />
              </td>
              <td>
                <Timestamp value={task.created_at} />
              </td>
              <td>
                <Link
                  className="icon-link"
                  href={`/tasks/detail/?ref=${encodeURIComponent(task.task_ref)}`}
                  aria-label={`Inspect ${taskTitle(task)} ${task.task_ref}`}
                >
                  <ArrowUpRight size={17} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
