import { test, expect, requireStack, login } from "./helpers";

const ADMIN = { email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@x.io", pw: process.env.E2E_ADMIN_PW ?? "ChangeMe!1" };
const MEMBER = { email: process.env.E2E_MEMBER_EMAIL ?? "e2e-member@x.io", pw: process.env.E2E_MEMBER_PW ?? "Member!1" };

test.beforeEach(async ({ page }) => { await requireStack(page); });

test("full lifecycle: login → create from template → edit config → submit → watch → result → download", async ({ page }) => {
  // 1. log in (handle forced first-login change if presented)
  await login(page, ADMIN.email, ADMIN.pw);
  if (page.url().includes("/change-password")) {
    await page.getByLabel("Current password").fill(ADMIN.pw);
    await page.getByLabel("New password").fill("NewPass!234");
    await page.getByRole("button", { name: "Update password" }).click();
    ADMIN.pw = "NewPass!234";
  }
  await expect(page).toHaveURL(/\/(containers)?$/);

  // 2. create a container from a template
  await page.goto("/containers/new");
  await page.getByText("Research assistant", { exact: false }).first().click();
  const name = `e2e-${Date.now()}`;
  await page.getByLabel("Name").fill(name);
  await page.getByRole("button", { name: "Create container" }).click();
  await expect(page).toHaveURL(/\/containers\/con_/);

  // 3. edit config and see the assembled-prompt preview update
  await page.getByRole("link", { name: "Configuration" }).click();
  const editor = page.getByLabel("System prompt");
  await editor.fill("Cite every source by URL.");
  await expect(page.getByTestId("assembled-preview")).toContainText("Cite every source by URL.");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  // 4. submit a task
  await page.getByRole("link", { name: "Submit Task" }).click();
  await page.getByLabel("Prompt").fill("Write a one-line markdown report to /workspace/report.md saying hello.");
  await page.getByRole("button", { name: "Submit task" }).click();
  await expect(page).toHaveURL(/\/tasks\/tsk_/);

  // 5. watch events stream
  await expect(page.getByText(/task started/i)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("event-row").first()).toBeVisible();

  // 6. result + file download
  await expect(page.getByText(/completed/i)).toBeVisible({ timeout: 90_000 });
  const dl = page.getByRole("link", { name: /report\.md/i });
  await expect(dl).toBeVisible();
  const [download] = await Promise.all([page.waitForEvent("download"), dl.click()]);
  expect(await download.path()).toBeTruthy();
});

test("config edit applies to the next task only (not the in-flight one)", async ({ page }) => {
  await login(page, ADMIN.email, ADMIN.pw);
  // open an existing container
  await page.goto("/containers");
  await page.getByRole("link", { name: "Open" }).first().click();

  // submit task A (long-ish) and capture its snapshot driver/mode from history later
  await page.getByRole("link", { name: "Submit Task" }).click();
  await page.getByLabel("Prompt").fill("Task A: wait and write /workspace/a.md");
  await page.getByRole("button", { name: "Submit task" }).click();
  await expect(page).toHaveURL(/\/tasks\/tsk_/);
  const taskAUrl = page.url();

  // while A is in flight, change the system prompt
  await page.goto(taskAUrl.replace(/\/tasks\/.*/, "/config"));
  await page.getByLabel("System prompt").fill("CHANGED-FOR-NEXT-TASK");
  await page.getByRole("button", { name: "Save", exact: true }).click();

  // submit task B
  await page.getByRole("link", { name: "Submit Task" }).click();
  await page.getByLabel("Prompt").fill("Task B: write /workspace/b.md");
  await page.getByRole("button", { name: "Submit task" }).click();

  // history: A's snapshot does NOT contain CHANGED-FOR-NEXT-TASK; B's does
  await page.getByRole("link", { name: "History" }).click();
  await page.getByText("Task A: wait", { exact: false }).click();
  await expect(page.getByText("Config snapshot · ran with")).toBeVisible();
  await expect(page.getByText("CHANGED-FOR-NEXT-TASK")).toHaveCount(0);
  await page.getByText("Task B: write", { exact: false }).click();
  await expect(page.getByText("CHANGED-FOR-NEXT-TASK")).toBeVisible();
});

test("a member sees no admin Settings", async ({ page }) => {
  await login(page, MEMBER.email, MEMBER.pw);
  // Fleet panel always shows the Containers link
  await expect(page.getByRole("link", { name: "Containers" })).toBeVisible();
  // Settings items live in the Settings section panel
  await page.getByRole("link", { name: "Settings" }).click();
  await expect(page.getByRole("link", { name: "Templates" })).toBeVisible(); // members can clone
  await expect(page.getByRole("link", { name: "Users" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "API keys" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Credentials" })).toHaveCount(0);
  // and direct navigation is guarded
  await page.goto("/settings/users");
  await expect(page).toHaveURL(/\/$/);
});
