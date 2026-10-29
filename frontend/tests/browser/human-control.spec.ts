import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { tmpdir } from "node:os";
import { mkdir } from "node:fs/promises";

const root = path.resolve("..");
const screenshots = path.join(
  tmpdir(),
  "ghost-frontend-phase4-human-regression-evidence",
);
let worker: ChildProcessWithoutNullStreams;
let pairingCode = "";
let waiting: ((value: Record<string, unknown>) => void) | null = null;

async function start() {
  if (
    await fetch("http://127.0.0.1:3000/health").then(
      () => true,
      () => false,
    )
  )
    throw new Error("Port 3000 is occupied; refusing to touch another service");
  const directory = path.join(
    tmpdir(),
    `ghost-offline-frontend-phase2-${crypto.randomUUID()}`,
  );
  worker = spawn(
    path.join(root, "member_a_backend/nvidia backend/.venv/Scripts/python.exe"),
    ["-B", path.resolve("tests/browser_worker.py"), directory, "--initialize"],
    { cwd: root, windowsHide: true, stdio: "pipe" },
  );
  await new Promise<void>((resolve, reject) => {
    worker.once("error", reject);
    worker.once("exit", (code) => {
      if (code) reject(new Error(`Disposable backend exited ${code}`));
    });
    createInterface({ input: worker.stdout }).on("line", (line) => {
      const value = JSON.parse(line) as Record<string, unknown>;
      if (typeof value.pairing_code === "string") {
        pairingCode = value.pairing_code;
        resolve();
      }
      waiting?.(value);
      waiting = null;
    });
    worker.stderr.on("data", () => {});
  });
  await expect
    .poll(async () => {
      try {
        return (await fetch("http://127.0.0.1:3000/health")).status;
      } catch {
        return 0;
      }
    })
    .toBe(200);
}
async function stop() {
  if (!worker || worker.exitCode !== null) return;
  const exit = new Promise<void>((resolve) =>
    worker.once("exit", () => resolve()),
  );
  worker.kill();
  await exit;
}
async function expireApproval(reference: string) {
  const reply = new Promise<Record<string, unknown>>((resolve) => {
    waiting = resolve;
  });
  worker.stdin.write(`expire_approval:${reference}\n`);
  expect((await reply).approval_expired).toBe(true);
}
async function control(message: string) {
  const reply = new Promise<Record<string, unknown>>((resolve) => {
    waiting = resolve;
  });
  worker.stdin.write(`${message}\n`);
  return reply;
}
async function pair(page: Page) {
  await page.goto("/");
  await page.getByLabel("Local pairing code").fill(pairingCode);
  await page.getByRole("button", { name: "Enter control room" }).click();
  await expect(
    page.getByRole("heading", { name: "Your agent. Your call." }),
  ).toBeVisible();
}
async function createPlanned(
  page: Page,
  profile:
    "document_simulation_v1" | "email_draft_v1" = "document_simulation_v1",
) {
  return page.evaluate(async (profileId) => {
    const session = (await (await fetch("/api/app/v1/session")).json()).data;
    const documents = (await (await fetch("/api/app/v1/documents")).json())
      .data;
    const command = async (url: string, body: object) => {
      const response = await fetch(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Ghost-CSRF": session.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error(`Synthetic setup command returned ${response.status}`);
      return (await response.json()).data;
    };
    const task = await command("/api/app/v1/tasks", {
      profile_id: profileId,
      resource_id:
        profileId === "document_simulation_v1"
          ? documents.items[0].resource_id
          : null,
    });
    const planning = await command(
      `/api/app/v1/tasks/${task.task_ref}/planning`,
      {
        user_request:
          profileId === "document_simulation_v1"
            ? "Summarize this synthetic document, but never share the original."
            : "Prepare a synthetic email draft using the fixed template.",
      },
    );
    return {
      taskRef: task.task_ref as string,
      approvalRef: planning.approval_ref as string,
    };
  }, profile);
}
async function review(page: Page, approvalRef: string) {
  await page.goto(`/approvals/detail/?ref=${approvalRef}`);
  await expect(
    page.getByRole("heading", { name: "Review permission." }),
  ).toBeVisible();
}
async function decide(
  page: Page,
  action: "Approve request" | "Reject request" | "Revoke permission",
) {
  await page.getByRole("button", { name: action, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: `${action}?`, exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: action, exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator(".error-panel")).toHaveCount(0);
}
async function screenshot(
  page: Page,
  name: string,
  width: number,
  height = width === 390 ? 844 : 1000,
) {
  const browserDirectory = path.join(
    screenshots,
    test.info().project.name || "chromium",
  );
  await page.setViewportSize({ width, height });
  await page.evaluate(async () => {
    await document.fonts.ready;
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(browserDirectory, `${name}-${width}-viewport.png`),
    fullPage: false,
  });
  await page.screenshot({
    path: path.join(browserDirectory, `${name}-${width}.png`),
    fullPage: true,
  });
}
async function attemptContinuation(page: Page, taskRef: string) {
  return page.evaluate(async (ref) => {
    const session = (await (await fetch("/api/app/v1/session")).json()).data;
    const response = await fetch(`/api/app/v1/tasks/${ref}/workflow/continue`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Ghost-CSRF": session.csrf_token,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: "{}",
    });
    return {
      status: response.status,
      code: (await response.json()).error?.code,
    };
  }, taskRef);
}

test.describe("Phase 2 real owner controls", () => {
  test.beforeEach(async ({ page }) => {
    await mkdir(screenshots, { recursive: true });
    await start();
    await pair(page);
  });
  test.afterEach(async () => {
    await stop();
  });

  test("queue, exact review, keyboard confirmation, explicit continuation and genuine record inspection", async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    await page.getByRole("link", { name: "Create task", exact: true }).click();
    await page
      .getByLabel(/Select authorized catalog metadata/)
      .selectOption({ index: 1 });
    await page
      .getByRole("button", { name: "Create task", exact: true })
      .click();
    await page
      .getByLabel("Your request")
      .fill("Summarize this synthetic document, but never share the original.");
    await page
      .getByRole("button", { name: "Start simulated planning" })
      .click();
    await expect(
      page.locator("#approval").getByText("Pending", { exact: true }),
    ).toBeVisible();
    const taskRef = new URL(page.url()).searchParams.get("ref")!;
    await page.goto("/");
    await expect(
      page.getByRole("link", { name: "Inspect pending request" }),
    ).toBeVisible();
    await screenshot(page, "dashboard-pending", 1440);
    await screenshot(page, "dashboard-pending", 390);
    await page.goto("/approvals/");
    await expect(
      page.getByRole("link", { name: "Inspect request", exact: true }),
    ).toHaveCount(1);
    await screenshot(page, "approval-center", 1440);
    await screenshot(page, "approval-center", 390);
    await page
      .getByRole("link", { name: "Inspect request", exact: true })
      .click();
    await expect(
      page.getByText("Only this request.", { exact: true }),
    ).toBeVisible();
    for (const width of [1440, 768, 390])
      await screenshot(page, "approval-pending", width);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page
      .getByText("Exact task and operation binding", { exact: true })
      .click();
    await expect(page.locator(".technical-details[open]")).toContainText(
      taskRef,
    );
    await page
      .getByText("Exact task and operation binding", { exact: true })
      .click();
    const decisions: string[] = [],
      continuations: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/decision"))
        decisions.push(r.postDataJSON().resolution);
      if (r.method() === "POST" && r.url().endsWith("/continue"))
        continuations.push(r.headers()["idempotency-key"]);
    });
    const approve = page.getByRole("button", {
      name: "Approve request",
      exact: true,
    });
    await approve.click();
    const dialog = page.getByRole("dialog", {
      name: "Approve request?",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(15);
    expect(bounds!.y).toBeGreaterThanOrEqual(15);
    await expect(dialog.getByRole("button", { name: "Go back" })).toBeFocused();
    expect(decisions).toEqual([]);
    expect(continuations).toEqual([]);
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .focus();
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() =>
        Boolean(document.activeElement?.closest("dialog")),
      ),
    ).toBe(true);
    await page.keyboard.press("Escape");
    await expect(approve).toBeFocused();
    await approve.click();
    await expect(dialog).toBeVisible();
    await screenshot(page, "approval-confirmation", 1440);
    await screenshot(page, "approval-confirmation", 390);
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .dblclick();
    await expect(
      page.locator(".page-heading").getByText("Approved", { exact: true }),
    ).toBeVisible();
    expect(decisions).toEqual(["APPROVE"]);
    expect(continuations).toEqual([]);
    await screenshot(page, "approval-approved", 1440);
    await page.getByRole("link", { name: "Open task & continuation" }).click();
    const continueButton = page.getByRole("button", {
      name: "Continue workflow",
      exact: true,
    });
    await expect(continueButton).toBeEnabled();
    await screenshot(page, "continuation-ready", 1440);
    await continueButton.click();
    const continuationDialog = page.getByRole("dialog", {
      name: "Continue this workflow?",
    });
    await expect(continuationDialog).toBeVisible();
    await expect(continuationDialog).toContainText("SAFE_STOPPED");
    expect(continuations).toEqual([]);
    await screenshot(page, "continuation-confirmation", 1440);
    await continuationDialog
      .getByRole("button", { name: "Continue workflow", exact: true })
      .click();
    await expect(page.locator(".rail-node").nth(4)).toContainText(
      "SAFE_STOPPED",
    );
    await expect(page.locator(".rail-node").nth(5)).toContainText(
      "Not executed",
    );
    await expect(continueButton).toBeDisabled();
    expect(continuations).toHaveLength(1);
    await screenshot(page, "workflow-safe-stopped", 1440);
    await screenshot(page, "workflow-safe-stopped", 390);
    await page
      .getByRole("button", { name: "Inspect human decision record" })
      .click();
    const record = page.getByRole("dialog", {
      name: "Human decision",
      exact: true,
    });
    await expect(record).toContainText("APPROVED");
    await screenshot(page, "decision-record", 390);
    await record.getByRole("button", { name: "Close record" }).click();
    await expect(
      page.getByRole("button", { name: "Inspect human decision record" }),
    ).toBeFocused();
    await page.goto("/approvals/");
    await expect(
      page.getByText("No pending decisions in this page"),
    ).toBeVisible();
    expect(errors).toEqual([]);
    // An explicit test replay of an acknowledged metadata command uses the same key.
    const replay = await page.evaluate(
      async ({ ref, key }) => {
        const session = (await (await fetch("/api/app/v1/session")).json())
          .data;
        const response = await fetch(
          `/api/app/v1/tasks/${ref}/workflow/continue`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Ghost-CSRF": session.csrf_token,
              "Idempotency-Key": key,
            },
            body: "{}",
          },
        );
        const body = await response.json();
        return {
          status: response.status,
          replayed: body.replayed,
          phase: body.data?.phase,
        };
      },
      { ref: taskRef, key: continuations[0] },
    );
    expect(replay).toEqual({ status: 200, replayed: true, phase: "RESUMED" });
  });

  test("reject and revoke deny subsequent continuation without external execution", async ({
    page,
  }) => {
    const first = await createPlanned(page);
    await review(page, first.approvalRef);
    await decide(page, "Reject request");
    await expect(
      page.locator(".page-heading").getByText("Rejected", { exact: true }),
    ).toBeVisible();
    await page.goto(`/tasks/detail/?ref=${first.taskRef}`);
    await expect(
      page.getByRole("button", { name: "Continue workflow", exact: true }),
    ).toBeDisabled();
    expect(await attemptContinuation(page, first.taskRef)).toEqual({
      status: 409,
      code: "WORKFLOW_DENIED",
    });
    const second = await createPlanned(page);
    await review(page, second.approvalRef);
    await decide(page, "Approve request");
    await decide(page, "Revoke permission");
    await expect(
      page.locator(".page-heading").getByText("Revoked", { exact: true }),
    ).toBeVisible();
    await screenshot(page, "approval-revoked", 1440);
    await screenshot(page, "approval-revoked", 390);
    await page.goto(`/tasks/detail/?ref=${second.taskRef}`);
    await expect(
      page.getByRole("button", { name: "Continue workflow", exact: true }),
    ).toBeDisabled();
    expect(await attemptContinuation(page, second.taskRef)).toEqual({
      status: 409,
      code: "WORKFLOW_DENIED",
    });
    await expect(page.locator(".rail-node").nth(3)).toContainText("Revoked");
    await expect(page.locator(".rail-node").nth(5)).toContainText(
      "Not executed",
    );
  });

  test("stale and expired confirmations refetch current authority without submitting approval", async ({
    page,
  }) => {
    const first = await createPlanned(page);
    await review(page, first.approvalRef);
    const resolutions: string[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().endsWith("/decision"))
        resolutions.push(r.postDataJSON().resolution);
    });
    await page
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Approve request?",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    await page.evaluate(async (ref) => {
      const session = (await (await fetch("/api/app/v1/session")).json()).data;
      const response = await fetch(`/api/app/v1/approvals/${ref}/decision`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Ghost-CSRF": session.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ resolution: "REJECT" }),
      });
      if (!response.ok)
        throw new Error(`Decision setup failed: ${response.status}`);
    }, first.approvalRef);
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    await expect(page.locator(".error-panel")).toContainText(
      "This review changed",
    );
    await expect(
      page.locator(".page-heading").getByText("Rejected", { exact: true }),
    ).toBeVisible();
    expect(resolutions).toEqual(["REJECT"]);
    const second = await createPlanned(page);
    await review(page, second.approvalRef);
    await page
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    await expect(dialog).toBeVisible();
    await expireApproval(second.approvalRef);
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    await expect(
      page.locator(".page-heading").getByText("Expired", { exact: true }),
    ).toBeVisible();
    expect(resolutions).toEqual(["REJECT"]);
    await expect(
      page.getByRole("button", { name: "Approve request", exact: true }),
    ).toHaveCount(0);
    await screenshot(page, "approval-expired", 390);
  });

  test("a lost real continuation acknowledgment never retries and stays locked across navigation", async ({
    page,
  }) => {
    const task = await createPlanned(page);
    await review(page, task.approvalRef);
    await decide(page, "Approve request");
    await page.goto(`/tasks/detail/?ref=${task.taskRef}`);
    let calls = 0;
    await page.route(
      `**/api/app/v1/tasks/${task.taskRef}/workflow/continue`,
      async (route) => {
        calls++;
        const response = await route.fetch();
        expect(response.status()).toBe(200);
        await route.abort("failed");
      },
    );
    await page
      .getByRole("button", { name: "Continue workflow", exact: true })
      .click();
    await page
      .getByRole("dialog", { name: "Continue this workflow?" })
      .getByRole("button", { name: "Continue workflow", exact: true })
      .click();
    await expect(page.locator("#workflow")).toContainText(
      "A command has an uncertain outcome",
    );
    await expect(page.locator(".rail-node").nth(4)).toContainText(
      "SAFE_STOPPED",
    );
    expect(calls).toBe(1);
    await page.getByRole("link", { name: "Approvals", exact: true }).click();
    await page.getByRole("link", { name: "Tasks", exact: true }).click();
    await page.locator(".task-name").first().click();
    await expect(page.locator("#workflow")).toContainText(
      "A command has an uncertain outcome",
    );
    await expect(
      page.getByRole("button", { name: "Continue workflow", exact: true }),
    ).toBeDisabled();
    expect(calls).toBe(1);
    await screenshot(page, "continuation-uncertain", 1440);
  });

  test("exact synthetic email scope is readable on mobile and absent from audit records", async ({
    page,
  }) => {
    const task = await createPlanned(page, "email_draft_v1");
    await review(page, task.approvalRef);
    await expect(
      page.getByRole("heading", { name: "Exact email body" }),
    ).toBeVisible();
    const body = await page.locator(".review-email pre").innerText();
    expect(body.length).toBeGreaterThan(0);
    await screenshot(page, "approval-email", 1440);
    await screenshot(page, "approval-email", 390);
    await page
      .getByRole("button", { name: "Reject request", exact: true })
      .click();
    const dialog = page.getByRole("dialog", { name: "Reject request?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Go back" }).click();
    await expect(
      page.getByRole("button", { name: "Reject request", exact: true }),
    ).toBeFocused();
    await page.goto(`/tasks/detail/?ref=${task.taskRef}`);
    await expect(page.locator(".timeline-panel")).not.toContainText(body);
  });

  test("approval mutations retain CSRF/Origin checks and an expired confirmation cannot submit", async ({
    page,
  }) => {
    const task = await createPlanned(page);
    await review(page, task.approvalRef);
    const withoutCsrf = await page.evaluate(async (ref) => {
      const response = await fetch(`/api/app/v1/approvals/${ref}/decision`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ resolution: "APPROVE" }),
      });
      return {
        status: response.status,
        code: (await response.json()).error.code,
      };
    }, task.approvalRef);
    expect(withoutCsrf).toEqual({ status: 403, code: "CSRF_INVALID" });
    const foreign = await page.request.post(
      `/api/app/v1/approvals/${task.approvalRef}/decision`,
      {
        headers: {
          Origin: "https://foreign.test",
          "Idempotency-Key": crypto.randomUUID(),
        },
        data: { resolution: "APPROVE" },
      },
    );
    expect(foreign.status()).toBe(403);
    expect((await foreign.json()).error.code).toBe("ORIGIN_FORBIDDEN");
    let submissions = 0;
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().endsWith("/decision"))
        submissions++;
    });
    await page
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Approve request?",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    expect((await control("expire")).expired).toBe(true);
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    await expect(page.getByText(/Your session ended/)).toBeVisible();
    expect(submissions).toBe(0);
    await screenshot(page, "approval-session-expired", 390);
    await control("pair");
    await pair(page);
    await review(page, task.approvalRef);
    await expect(
      page.locator(".page-heading").getByText("Pending", { exact: true }),
    ).toBeVisible();
    expect(submissions).toBe(0);
  });
});
