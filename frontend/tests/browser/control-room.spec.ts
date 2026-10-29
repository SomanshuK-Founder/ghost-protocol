import { test, expect } from "@playwright/test";
import type { Browser, Page } from "@playwright/test";
import { spawn } from "node:child_process";
import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import { tmpdir } from "node:os";
import { mkdir } from "node:fs/promises";

const root = path.resolve("..");
const directory = path.join(
  tmpdir(),
  `ghost-offline-frontend-${crypto.randomUUID()}`,
);
const evidenceDirectory = path.join(
  tmpdir(),
  "ghost-frontend-phase4-regression-evidence",
);
let worker: ChildProcessWithoutNullStreams;
let pairingCode = "";
let waitMessage: ((value: Record<string, unknown>) => void) | null = null;
let persistedTask = "";

async function start(initialize: boolean, pairing = true) {
  const occupied = await fetch("http://127.0.0.1:3000/health").then(
    () => true,
    () => false,
  );
  if (occupied)
    throw new Error(
      "Port 3000 is occupied; browser tests refuse to touch an existing service",
    );
  worker = spawn(
    path.join(root, "member_a_backend/nvidia backend/.venv/Scripts/python.exe"),
    [
      "-B",
      path.resolve("tests/browser_worker.py"),
      directory,
      ...(initialize ? ["--initialize"] : []),
      ...(!pairing ? ["--auth-disabled"] : []),
    ],
    { cwd: root, windowsHide: true, stdio: "pipe" },
  );
  const initial = new Promise<void>((resolve, reject) => {
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
      if (value.auth_disabled === true) resolve();
      waitMessage?.(value);
      waitMessage = null;
    });
  });
  // Never print private pipes: a pairing code must not enter test evidence.
  worker.stderr.on("data", () => {});
  await initial;
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
async function control(command: "pair" | "expire") {
  const reply = new Promise<Record<string, unknown>>((resolve) => {
    waitMessage = resolve;
  });
  worker.stdin.write(`${command}\n`);
  return reply;
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
  await control("pair");
  await page.goto("/");
  await expect(page.getByLabel("Local pairing code")).toBeEnabled();
  await page.getByLabel("Local pairing code").fill(pairingCode);
  const login = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().endsWith("/session/login"),
  );
  await page.getByRole("button", { name: "Enter control room" }).click();
  const policy = await (await login).headerValue("set-cookie");
  expect(
    Boolean(
      policy &&
      /;\s*HttpOnly/i.test(policy) &&
      /;\s*SameSite=Strict/i.test(policy) &&
      /;\s*Path=\//i.test(policy),
    ),
  ).toBe(true);
  await expect(
    page.getByRole("heading", { name: "Your agent. Your call." }),
  ).toBeVisible();
}
async function screenshot(page: Page, filename: string) {
  const browserDirectory = path.join(
    evidenceDirectory,
    test.info().project.name || "chromium",
  );
  await page.evaluate(async () => {
    await document.fonts.ready;
    window.scrollTo({ top: 0, behavior: "instant" });
  });
  await page.screenshot({
    path: path.join(
      browserDirectory,
      filename.replace(".png", "-viewport.png"),
    ),
    fullPage: false,
  });
  await page.screenshot({
    path: path.join(browserDirectory, filename),
    fullPage: true,
  });
}
async function noOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
}

test.describe.serial("real local application control room", () => {
  test.beforeAll(async () => {
    await mkdir(evidenceDirectory, { recursive: true });
    await start(true);
  });
  test.afterAll(async () => {
    await stop();
  });

  test("pair, create, plan, inspect real evidence, and responsive navigation", async ({
    page,
    browser,
    browserName,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    const networkErrors: string[] = [];
    page.on("response", (response) => {
      if (response.status() >= 400)
        networkErrors.push(
          `${response.status()} ${new URL(response.url()).pathname}`,
        );
    });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto("/");
    await expect(page).toHaveTitle("Ghost Protocol — Control room");
    await expect(page.getByLabel("Local pairing code")).toBeEnabled();
    await screenshot(page, "pairing-1440.png");
    await pair(page);
    await expect(
      page.getByText("Your next intention starts here"),
    ).toBeVisible();
    await screenshot(page, "overview-empty-1440.png");
    const cookies = await page.context().cookies();
    const cookie = cookies.find((c) => c.name === "ghost_demo_session");
    expect(cookie?.httpOnly).toBe(true);
    if (browserName === "webkit" && process.platform === "win32") {
      test.info().annotations.push({
        type: "security limitation",
        description:
          "Windows WebKit reports None and does not enforce Strict in an isolated synthetic-cookie probe; wire Strict is asserted. Not qualified for session-security acceptance.",
      });
      expect(cookie?.sameSite).toBe("None");
    } else expect(cookie?.sameSite).toBe("Strict");
    expect(await page.evaluate(() => document.cookie)).not.toContain(
      "ghost_demo_session",
    );
    expect(
      await page.evaluate(() => [localStorage.length, sessionStorage.length]),
    ).toEqual([0, 0]);
    await page.getByRole("link", { name: "Create task", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Create task", exact: true }),
    ).toBeDisabled();
    await page
      .getByLabel(/Select authorized catalog metadata/)
      .selectOption({ index: 1 });
    let creates = 0;
    page.on("request", (r) => {
      if (
        r.method() === "POST" &&
        new URL(r.url()).pathname === "/api/app/v1/tasks"
      )
        creates++;
    });
    await page
      .getByRole("button", { name: "Create task", exact: true })
      .click();
    await expect(
      page.getByRole("heading", { name: "Planning workspace" }),
    ).toBeVisible();
    expect(creates).toBe(1);
    persistedTask = new URL(page.url()).searchParams.get("ref") ?? "";
    expect(persistedTask).toMatch(/^task_/);
    const startButton = page.getByRole("button", {
      name: "Start simulated planning",
    });
    await expect(startButton).toBeDisabled();
    await page
      .getByLabel("Your request")
      .fill("Summarize this synthetic document, but never share the original.");
    await screenshot(page, "task-unplanned-1440.png");
    await startButton.click();
    await expect(
      page.getByText("Simulated planning · mock model", { exact: true }),
    ).toBeVisible({ timeout: 25_000 });
    await expect(
      page.getByRole("heading", { name: "Operation records" }),
    ).toBeVisible();
    await expect(
      page.locator("#approval").getByText("Pending", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Not executed", { exact: true }).first(),
    ).toBeVisible();
    await expect(page.locator(".rail-node")).toHaveCount(6);
    await expect(page.locator(".rail-node").nth(2)).toContainText(
      "Approval required",
    );
    await expect(page.locator(".rail-node").nth(5)).toContainText(
      "Not executed",
    );
    for (const width of [1440, 1280, 768, 390, 1920, 1366]) {
      await page.setViewportSize({
        width,
        height:
          width === 390
            ? 844
            : width === 1920
              ? 1080
              : width === 1366
                ? 768
                : 900,
      });
      await noOverflow(page);
      await screenshot(page, `task-planned-${width}.png`);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("button", { name: "Open navigation" }).click();
    await expect(
      page.getByRole("dialog", { name: "Ghost Protocol" }),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("dialog", { name: "Ghost Protocol" }),
    ).not.toBeVisible();
    await page.getByRole("button", { name: "Open navigation" }).click();
    await page
      .getByRole("dialog")
      .getByRole("link", { name: "Overview" })
      .click();
    await expect(
      page.getByRole("heading", { name: "Your agent. Your call." }),
    ).toBeVisible();
    await expect(
      page.getByText("awaiting", { exact: false }).first(),
    ).toBeVisible();
    await screenshot(page, "overview-connected-390.png");
    await page.setViewportSize({ width: 1440, height: 1000 });
    await screenshot(page, "overview-connected-1440.png");
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(
      await page.evaluate(
        () =>
          getComputedStyle(document.querySelector(".button")!)
            .transitionDuration,
      ),
    ).toBe("0s");
    expect(networkErrors).toEqual([]);
    expect(errors).toEqual([]);
    await verifySecurity(page, browser);
  });

  test("expiry clears planning draft; logout invalidates session and restores focus", async ({
    page,
  }) => {
    await pair(page);
    await page.goto("/tasks/new/");
    await page.getByLabel("Email draft", { exact: false }).check();
    await page
      .getByRole("button", { name: "Create task", exact: true })
      .click();
    await page.getByLabel("Your request").fill("Private draft must disappear");
    await control("expire");
    const expiredResponse = page.waitForResponse(
      async (response) =>
        response.status() === 401 &&
        (await response.json()).error?.code === "SESSION_EXPIRED",
    );
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expiredResponse;
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    await expect(page.getByText(/Your session ended/)).toBeVisible();
    await expect(page.getByText("Private draft must disappear")).toHaveCount(0);
    await pair(page);
    await page.getByRole("button", { name: "Log out", exact: true }).click();
    const dialog = page.getByRole("dialog", {
      name: "End this local session?",
    });
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(
      page.getByRole("button", { name: "Log out", exact: true }),
    ).toBeFocused();
    await page.getByRole("button", { name: "Log out", exact: true }).click();
    let releaseLogout!: () => void;
    const acknowledgment = new Promise<void>((resolve) => {
      releaseLogout = resolve;
    });
    await page.route("**/api/app/v1/session/logout", async (route) => {
      const response = await route.fetch();
      await acknowledgment;
      await route.fulfill({ response });
    });
    await dialog.getByRole("button", { name: "Log out", exact: true }).click();
    await expect(
      dialog.getByRole("button", { name: "Ending session…", exact: true }),
    ).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeVisible();
    releaseLogout();
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    expect(
      (await page.context().cookies()).some(
        (c) => c.name === "ghost_demo_session" && c.value === "",
      ),
    ).toBe(false);
  });

  test("real approval and continuation records render SAFE_STOPPED without execution", async ({
    page,
  }) => {
    await pair(page);
    await page.goto(`/tasks/detail/?ref=${persistedTask}`);
    await expect(
      page.locator("#approval").getByText("Pending", { exact: true }),
    ).toBeVisible();
    // Test-only owner commands create real stored states; no execution service is invoked.
    const result = await page.evaluate(async (taskRef) => {
      const session = (await (await fetch("/api/app/v1/session")).json()).data;
      const task = (await (await fetch(`/api/app/v1/tasks/${taskRef}`)).json())
        .data;
      const command = (path: string, body: object) =>
        fetch(path, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Ghost-CSRF": session.csrf_token,
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify(body),
        });
      const approval = await command(
        `/api/app/v1/approvals/${task.approval_ref}/decision`,
        { resolution: "APPROVE" },
      );
      const continued = await command(
        `/api/app/v1/tasks/${taskRef}/workflow/continue`,
        {},
      );
      return { approved: approval.status, continued: continued.status };
    }, persistedTask);
    expect(result).toEqual({ approved: 200, continued: 200 });
    await page.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(page.locator(".rail-node").nth(4)).toContainText(
      "SAFE_STOPPED",
    );
    await expect(page.locator(".rail-node").nth(5)).toContainText(
      "Not executed",
    );
    await screenshot(page, "task-safe-stopped-1280.png");
    await expect(
      page.getByRole("button", { name: /dispatch|send email|execute/i }),
    ).toHaveCount(0);
    const rejected = await page.evaluate(async () => {
      const session = (await (await fetch("/api/app/v1/session")).json()).data;
      const key = crypto.randomUUID();
      const options = {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Ghost-CSRF": session.csrf_token,
          "Idempotency-Key": key,
        },
        body: JSON.stringify({
          profile_id: "email_draft_v1",
          resource_id: null,
        }),
      };
      const first = await fetch("/api/app/v1/tasks", options);
      const original = await first.json();
      const replay = await fetch("/api/app/v1/tasks", options);
      const replayed = await replay.json();
      return {
        first: first.status,
        replay: replay.status,
        sameTask: original.data.task_ref === replayed.data.task_ref,
        replayed: replayed.replayed,
      };
    });
    expect(rejected).toEqual({
      first: 201,
      replay: 200,
      sameTask: true,
      replayed: true,
    });
  });

  test("not-found and disconnected states show honest recovery", async ({
    page,
  }) => {
    await pair(page);
    await page.goto("/tasks/detail/?ref=task_missing_synthetic");
    await expect(page.locator(".error-panel[role=alert]")).toContainText(
      "This record is unavailable",
    );
    await page.context().setOffline(true);
    await page.getByRole("button", { name: "Refresh state" }).click();
    await expect(page.locator(".error-panel[role=alert]")).toContainText(
      "Connection unavailable",
    );
    await page.context().setOffline(false);
  });

  test("restart persists task and invalidates the prior browser cookie", async ({
    page,
  }) => {
    await stop();
    await start(false);
    await pair(page);
    await stop();
    await start(false);
    await page.goto(`/tasks/detail/?ref=${persistedTask}`);
    await expect(page.getByLabel("Local pairing code")).toBeVisible();
    await pair(page);
    await page.goto(`/tasks/detail/?ref=${persistedTask}`);
    await expect(
      page.getByRole("heading", { name: "Document assistant", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("Simulated planning · mock model", { exact: true }),
    ).toBeVisible();
  });

  test("disabled authentication explains local operator setup", async ({
    page,
  }) => {
    await stop();
    await start(false, false);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/");
    await expect(page.locator(".error-panel[role=alert]")).toContainText(
      "Local pairing is off",
    );
    await expect(page.getByLabel("Local pairing code")).toBeDisabled();
    await expect(
      page.getByRole("button", { name: "Enter control room" }),
    ).toBeDisabled();
    await noOverflow(page);
    await screenshot(page, "pairing-disabled-390.png");
  });
});

async function verifySecurity(page: Page, browser: Browser) {
  const csrfFailure = await page.evaluate(async () => {
    const response = await fetch("/api/app/v1/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: "email_draft_v1", resource_id: null }),
    });
    return { status: response.status, body: await response.json() };
  });
  expect(csrfFailure.status).toBe(403);
  expect(csrfFailure.body.error.code).toBe("CSRF_INVALID");
  for (const route of [
    "/api/gateway/v1/execute",
    "/api/workflow/v1/continue",
    "/docs",
    "/openapi.json",
  ])
    expect((await page.request.get(route)).status()).toBe(404);
  const denied = await page.request.get("/api/app/v1/tasks", {
    headers: { Origin: "https://foreign.test" },
  });
  expect(denied.status()).toBe(403);
  const forbiddenCredential = await page.request.get("/api/app/v1/tasks", {
    headers: {
      Origin: "http://127.0.0.1:3000",
      Authorization: "Bearer synthetic-forbidden",
    },
  });
  expect(forbiddenCredential.status()).toBe(403);
  const foreign = await browser.newContext();
  expect(
    (
      await foreign.request.get(`/api/app/v1/tasks/${persistedTask}`, {
        headers: { Origin: "http://127.0.0.1:3000" },
      })
    ).status(),
  ).toBe(401);
  await foreign.close();
}
