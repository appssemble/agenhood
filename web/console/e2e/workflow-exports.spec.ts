import { test, expect, requireStack, login } from "./helpers";

const ADMIN = {
  email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@x.io",
  pw: process.env.E2E_ADMIN_PW ?? "ChangeMe!1",
};

test.beforeEach(async ({ page }) => { await requireStack(page); });

// Builder round-trip: exports persist through save + reload (workflow file
// transfer spec, console section). Requires at least one prompt and one
// container in the stack (console.spec.ts's lifecycle test creates both).
test("workflow step exports round-trip through the builder", async ({ page }) => {
  await login(page, ADMIN.email, ADMIN.pw);
  // Wait for the app's own post-login redirect before driving further
  // navigation ourselves — login() only awaits the click, not the in-flight
  // /v1/auth/me fetch inside Login.tsx's onSubmit; an immediate goto() here
  // would race and abort that fetch, losing the session cookie.
  await page.waitForURL((url) => url.pathname !== "/login");
  if (page.url().includes("/change-password")) {
    await page.getByLabel("Current password").fill(ADMIN.pw);
    await page.getByLabel("New password").fill("NewPass!234");
    await page.getByRole("button", { name: "Update password" }).click();
    await page.waitForURL((url) => url.pathname !== "/change-password");
  }

  const name = `e2e exports ${Date.now()}`;
  await page.goto("/workflows/new");
  await page.getByLabel("Workflow name").fill(name);

  await page.getByRole("button", { name: /add step/i }).click();
  // exact: true — "Prompt" would otherwise also match the step's "Edit
  // prompt" toggle button, whose aria-label contains it as a substring.
  await page.getByLabel("Prompt", { exact: true }).click();
  await page.getByRole("option").first().click();
  await page.getByLabel("Container", { exact: true }).click();
  await page.getByRole("option").first().click();

  await page.getByRole("button", { name: /add file/i }).click();
  await page.getByLabel("Export path 1").fill("dist/**");

  await page.getByRole("button", { name: "Save workflow" }).click();
  await expect(page).toHaveURL(/\/workflows$/);

  // Reopen the workflow's edit form: the list card for this workflow has its
  // own "Edit" link straight to the builder (Workflows.tsx renders one per
  // card, separate from the stretched "Open" link that goes to the detail
  // page) — scope to the card so it's unambiguous among other workflows.
  const card = page.locator(".wf-card", { hasText: name });
  await card.getByRole("link", { name: "Edit" }).click();
  await expect(page.getByLabel("Export path 1")).toHaveValue("dist/**");
});
