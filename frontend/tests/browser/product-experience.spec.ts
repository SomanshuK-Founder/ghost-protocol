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
  "ghost-frontend-phase4-product-evidence",
);
let worker: ChildProcessWithoutNullStreams;
let pairingCode = "";

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
    `ghost-offline-frontend-phase3-${crypto.randomUUID()}`,
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

async function shot(page: Page, name: string, width: number) {
  const browserDirectory = path.join(
    screenshots,
    test.info().project.name || "chromium",
  );
  await page.setViewportSize({
    width,
    height: width === 390 ? 844 : width === 768 || width === 1280 ? 900 : 1080,
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
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
async function desktopMobile(page: Page, name: string) {
  for (const width of [768, 1280, 1920]) {
    await page.setViewportSize({ width, height: 1080 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
  await shot(page, name, 1440);
  await shot(page, name, 390);
}
async function settled(page: Page) {
  await expect(page.locator(".skeleton")).toHaveCount(0);
  await expect(page.locator(".error-panel")).toHaveCount(0);
}

test.describe("Phase 3 complete offline product", () => {
  test.beforeEach(async ({ page }) => {
    await mkdir(screenshots, { recursive: true });
    await start();
    await pair(page);
  });
  test.afterEach(async () => {
    await stop();
  });

  test("complete UI demo, genuine records, cursor pages and five responsive widths", async ({
    page,
  }) => {
    test.setTimeout(240_000);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    await page.getByRole("link", { name: "Create task", exact: true }).click();
    await page
      .getByLabel(/Select authorized catalog metadata/)
      .selectOption({ index: 1 });
    await desktopMobile(page, "task-creation");
    await page
      .getByRole("button", { name: "Create task", exact: true })
      .click();
    await page
      .getByLabel("Your request")
      .fill("Summarize this synthetic document, but never share the original.");
    await desktopMobile(page, "planning-workspace");
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
    await desktopMobile(page, "dashboard");
    await page.goto("/approvals/");
    await expect(
      page.getByRole("link", { name: "Inspect request", exact: true }),
    ).toHaveCount(1);
    await desktopMobile(page, "pending-approval");
    await page
      .getByRole("link", { name: "Inspect request", exact: true })
      .click();
    await expect(
      page.getByText("Only this request.", { exact: true }),
    ).toBeVisible();
    await desktopMobile(page, "approval-detail");
    await page
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    const dialog = page.getByRole("dialog", {
      name: "Approve request?",
      exact: true,
    });
    await expect(dialog).toBeVisible();
    await desktopMobile(page, "approval-review-dialog");
    await dialog
      .getByRole("button", { name: "Approve request", exact: true })
      .click();
    await expect(
      page.locator(".page-heading").getByText("Approved", { exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Open task & continuation" }).click();
    await page
      .getByRole("button", { name: "Continue workflow", exact: true })
      .click();
    const continuation = page.getByRole("dialog", {
      name: "Continue this workflow?",
    });
    await expect(continuation).toBeVisible();
    await desktopMobile(page, "continuation-dialog");
    await continuation
      .getByRole("button", { name: "Continue workflow", exact: true })
      .click();
    await expect(page.locator(".rail-node").nth(4)).toContainText(
      "SAFE_STOPPED",
    );
    await expect(page.locator(".rail-node").nth(5)).toContainText(
      "Not executed",
    );
    await desktopMobile(page, "safe-stopped");

    await page
      .getByRole("link", { name: "Open operation history", exact: true })
      .click();
    await expect(page.locator(".operation-record")).toHaveCount(1);
    await expect(page.locator(".operation-record")).toContainText(
      "Not executed",
    );
    await expect(
      page.getByText("The verified operation endpoint exposes no cursor", {
        exact: false,
      }),
    ).toBeVisible();
    await page
      .getByText("Operation metadata and references", { exact: true })
      .click();
    await expect(page.locator(".evidence-fields")).toContainText(taskRef);
    await desktopMobile(page, "operation-history");
    await page
      .getByRole("link", { name: "Inspect operation", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "A record, with provenance." }),
    ).toBeVisible();
    await expect(page.locator(".operation-record")).toHaveCount(1);
    await desktopMobile(page, "operation-detail");
    await page
      .getByRole("link", { name: "Open task audit", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Chronological timeline" }),
    ).toBeVisible();
    await page.getByLabel("Events per page", { exact: true }).selectOption("1");
    await expect(page.locator(".explorer-events > li")).toHaveCount(1);
    await page
      .getByText("Event details and references", { exact: true })
      .click();
    const first = await page
      .locator(".evidence-fields code")
      .first()
      .innerText();
    // Exercise copy without reading or replacing the user's operating-system clipboard.
    await page.evaluate(() =>
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            document.documentElement.dataset.copiedReference = value;
          },
        },
      }),
    );
    await page
      .getByRole("button", { name: "Copy event reference", exact: true })
      .click();
    expect(
      await page.locator("html").getAttribute("data-copied-reference"),
    ).toBe(first);
    await expect(
      page.getByRole("status").filter({ hasText: "Reference copied" }),
    ).toHaveCount(1);
    await page.evaluate(() =>
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: {
          writeText: async () => {
            throw new Error("Clipboard denied in isolated test");
          },
        },
      }),
    );
    await page
      .getByRole("button", { name: "Copy event reference", exact: true })
      .click();
    await expect(
      page.getByText(
        "Clipboard unavailable. Select the reference text to copy manually.",
        { exact: true },
      ),
    ).toBeVisible();
    await shot(page, "copy-fallback", 390);
    await page
      .locator(".page-controls")
      .last()
      .getByRole("button", { name: "Next page", exact: true })
      .click();
    await expect(page.locator(".explorer-events > li")).toHaveCount(1);
    await page
      .getByText("Event details and references", { exact: true })
      .click();
    expect(
      await page.locator(".evidence-fields code").first().innerText(),
    ).not.toBe(first);
    await page
      .locator(".page-controls")
      .last()
      .getByRole("button", { name: "First page", exact: true })
      .click();
    await page
      .getByLabel("Events per page", { exact: true })
      .selectOption("50");
    await expect(page.locator(".explorer-events > li")).not.toHaveCount(0);
    await expect(page.locator(".explorer-events")).toContainText(
      "Safe continuation stopped here (SAFE_STOPPED)",
    );
    await desktopMobile(page, "audit-explorer");
    const dates = await page
      .locator(".explorer-events > li > time")
      .evaluateAll((elements) =>
        elements.map((element) => element.getAttribute("datetime")!),
      );
    expect(dates.length).toBeGreaterThan(1);
    expect(dates).toEqual([...dates].sort());

    await page.goto("/documents/");
    await expect(page.locator(".document-card")).toHaveCount(2);
    await page
      .getByLabel("Documents per page", { exact: true })
      .selectOption("1");
    await expect(page.locator(".document-card")).toHaveCount(1);
    const documentName = await page.locator(".document-card h2").innerText();
    await page.getByText("Six catalog fields", { exact: true }).click();
    await expect(page.locator(".document-card dt")).toHaveCount(6);
    await expect(
      page.getByRole("button", {
        name: /read document|download|upload|share original/i,
      }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Next page", exact: true }).click();
    await expect(page.locator(".document-card h2")).not.toHaveText(
      documentName,
    );
    await page.getByRole("button", { name: "First page", exact: true }).click();
    await expect(page.locator(".document-card h2")).toHaveText(documentName);
    await page
      .getByLabel("Documents per page", { exact: true })
      .selectOption("10");
    await expect(page.locator(".document-card")).toHaveCount(2);
    await desktopMobile(page, "document-catalog");
    await page.goto("/settings/");
    await expect(
      page.getByText("The local session endpoint responded.", { exact: true }),
    ).toBeVisible();
    await desktopMobile(page, "settings-status");
    await page
      .getByRole("button", { name: "Check connection", exact: true })
      .click();
    await expect(
      page.getByText("The local session endpoint responded.", { exact: true }),
    ).toBeVisible();
    for (const [route, marker] of [
      [`/audit/?ref=${taskRef}`, "Chronological timeline"],
      [`/operations/?ref=${taskRef}`, "Authority isn’t execution."],
      ["/documents/", "Know what’s in scope."],
      ["/settings/", "Clarity is a capability."],
    ] as const) {
      await page.goto(route);
      await expect(
        page.getByRole("heading", { name: marker, exact: true }),
      ).toBeVisible();
      await settled(page);
      for (const width of [390, 768, 1280, 1440, 1920])
        await shot(page, `responsive-${route.split("/")[1]}`, width);
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(
      await page
        .locator(".button")
        .first()
        .evaluate((element) =>
          parseFloat(getComputedStyle(element).transitionDuration),
        ),
    ).toBeLessThanOrEqual(0.01);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Open navigation" }).click();
    const navigation = page.getByRole("dialog", {
      name: "Ghost Protocol",
      exact: true,
    });
    await expect(navigation).toBeVisible();
    await expect(
      navigation.getByRole("link", { name: "Documents", exact: true }),
    ).toBeVisible();
    await expect(
      navigation.getByText("Documents", { exact: true }),
    ).toBeVisible();
    await shot(page, "mobile-navigation", 390);
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Open navigation" }),
    ).toBeFocused();
    await page
      .getByRole("button", { name: "End local session", exact: true })
      .click();
    const logout = page.getByRole("dialog", {
      name: "End the local session?",
      exact: true,
    });
    await expect(
      logout.getByRole("button", { name: "Go back", exact: true }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(() =>
        Boolean(document.activeElement?.closest("dialog")),
      ),
    ).toBe(true);
    await shot(page, "logout-dialog", 390);
    await logout.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    expect(errors).toEqual([]);
  });

  test("task-scoped empty states, cancellation, cross-binding denial and navigation pages", async ({
    page,
  }) => {
    const planned = await createPlanned(page);
    const emptyRef = await page.evaluate(async () => {
      const session = (await (await fetch("/api/app/v1/session")).json()).data;
      const response = await fetch("/api/app/v1/tasks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Ghost-CSRF": session.csrf_token,
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          profile_id: "email_draft_v1",
          resource_id: null,
        }),
      });
      if (!response.ok)
        throw new Error(`Task setup returned ${response.status}`);
      return (await response.json()).data.task_ref as string;
    });
    await page.goto(`/operations/?ref=${emptyRef}`);
    await expect(
      page.getByText("No operation recorded", { exact: true }),
    ).toBeVisible();
    await desktopMobile(page, "operations-empty");
    await page.getByText("Browse task pages", { exact: true }).focus();
    await page.keyboard.press("Enter");
    await page.getByLabel("Tasks per page", { exact: true }).selectOption("1");
    await expect(
      page.getByRole("button", { name: "Next page", exact: true }).first(),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Next page", exact: true })
      .first()
      .click();
    await settled(page);
    await expect(page.getByLabel("Task scope", { exact: true })).toHaveValue(
      emptyRef,
    );
    await page.goto(`/audit/?ref=${emptyRef}`);
    await expect(
      page.getByText("No visible events in this page", { exact: true }),
    ).toBeVisible();
    await desktopMobile(page, "audit-empty");
    await page
      .getByLabel("Task scope", { exact: true })
      .selectOption(planned.taskRef);
    await expect(page.locator(".explorer-events > li")).not.toHaveCount(0);
    expect(new URL(page.url()).searchParams.get("ref")).toBe(planned.taskRef);
    await page.getByLabel("Task scope", { exact: true }).selectOption(emptyRef);
    await expect(
      page.getByText("No visible events in this page", { exact: true }),
    ).toBeVisible();
    const operationRef = await page.evaluate(
      async (ref) =>
        (await (await fetch(`/api/app/v1/tasks/${ref}/operations`)).json()).data
          .items[0].operation_ref as string,
      planned.taskRef,
    );
    await page.goto(
      `/operations/detail/?ref=${emptyRef}&operation=${operationRef}`,
    );
    await expect(page.locator(".error-panel")).toBeVisible();
    await expect(page.locator(".error-panel")).toContainText(
      "unavailable for the current session",
    );
    await desktopMobile(page, "operation-binding-denied");
    await page.goto(`/tasks/detail/?ref=${planned.taskRef}`);
    await expect(
      page.getByRole("button", { name: "Cancel task", exact: true }),
    ).toBeEnabled();
    await page
      .getByRole("button", { name: "Cancel task", exact: true })
      .click();
    const cancel = page.getByRole("dialog", {
      name: "Cancel this task?",
      exact: true,
    });
    await expect(cancel).toContainText("not an undo");
    await desktopMobile(page, "cancel-dialog");
    await cancel
      .getByRole("button", { name: "Cancel task", exact: true })
      .click();
    await expect(cancel).not.toBeVisible();
    await settled(page);
    await expect(
      page.getByRole("button", { name: "Cancel task", exact: true }),
    ).toBeDisabled();
    const state = await page.evaluate(async (ref) => {
      const task = (await (await fetch(`/api/app/v1/tasks/${ref}`)).json())
        .data;
      const operations = (
        await (await fetch(`/api/app/v1/tasks/${ref}/operations`)).json()
      ).data;
      return { authority: task.authority_state, operations: operations.items };
    }, planned.taskRef);
    expect(state.authority).toBe("CANCELLED");
    expect(state.operations[0].execution_status).toBe("NOT_EXECUTED");
    await page.goto(`/audit/?ref=${planned.taskRef}`);
    await expect(page.locator(".explorer-events")).toContainText("Revoked");
    await desktopMobile(page, "cancelled-audit");
  });

  test("real connection failures recover; read ownership and mutation protections remain intact", async ({
    page,
    context,
  }) => {
    const planned = await createPlanned(page);
    await page.goto("/settings/");
    await expect(
      page.getByText("The local session endpoint responded.", { exact: true }),
    ).toBeVisible();
    await context.setOffline(true);
    await page
      .getByRole("button", { name: "Check connection", exact: true })
      .click();
    await expect(page.locator(".error-panel")).toBeVisible();
    await expect(
      page.getByText("The local session endpoint responded.", { exact: true }),
    ).toHaveCount(0);
    await desktopMobile(page, "connection-error");
    await context.setOffline(false);
    await page
      .getByRole("button", { name: "Check connection", exact: true })
      .click();
    await expect(
      page.getByText("The local session endpoint responded.", { exact: true }),
    ).toBeVisible();
    const csrfStatus = await page.evaluate(
      async (ref) =>
        (
          await fetch(`/api/app/v1/tasks/${ref}/cancel`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": crypto.randomUUID(),
            },
            body: "{}",
          })
        ).status,
      planned.taskRef,
    );
    expect(csrfStatus).toBe(403);
    const foreignOrigin = await context.request.get("/api/app/v1/documents", {
      headers: { Origin: "https://example.invalid" },
    });
    expect(foreignOrigin.status()).toBe(403);
    await page
      .getByRole("button", { name: "End local session", exact: true })
      .click();
    await page
      .getByRole("dialog", { name: "End the local session?", exact: true })
      .getByRole("button", { name: "Log out", exact: true })
      .click();
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    for (const endpoint of [
      "/documents",
      `/tasks/${planned.taskRef}/operations`,
      `/tasks/${planned.taskRef}/timeline`,
    ]) {
      const response = await context.request.get(`/api/app/v1${endpoint}`, {
        headers: { Origin: "http://127.0.0.1:3000" },
      });
      expect(response.status()).toBe(401);
      expect(await response.text()).not.toContain(planned.taskRef);
    }
  });
});
