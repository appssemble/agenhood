import { test, expect, requireStack, login } from "./helpers";

// A user who belongs to two workspaces. Seed/admin must enrol this account in
// both; the test self-skips when only one workspace is present (single-tenant
// stack) or when no stack is reachable.
const MULTI = {
  email: process.env.E2E_MULTI_EMAIL ?? "e2e-multi@x.io",
  pw: process.env.E2E_MULTI_PW ?? "Multi!1",
};

test.beforeEach(async ({ page }) => { await requireStack(page); });

test("multi-tenant: switching the active workspace re-scopes the console", async ({ page }) => {
  await login(page, MULTI.email, MULTI.pw);
  if (page.url().includes("/change-password")) {
    test.skip(true, "first-login change required; seed a pre-rotated account");
  }

  // The TenantSwitcher trigger has aria-haspopup="listbox" and no aria-label;
  // its accessible name is the active workspace name (text content of inner <span>).
  // Using the ARIA attribute is more stable than matching by workspace name.
  const switcher = page.locator('button[aria-haspopup="listbox"]');
  const activeWorkspaceName = (await switcher.innerText()).trim();
  await switcher.click();

  // All workspace rows (plus the "New workspace" action) use role="option".
  // Exclude the "New workspace" action row when counting real workspace options.
  const allOptions = page.getByRole("option");
  const workspaceOptions = allOptions.filter({ hasNotText: /new workspace/i });
  const count = await workspaceOptions.count();
  if (count < 2) {
    test.skip(true, "account belongs to a single workspace — multi-tenant switch n/a");
  }

  // Pick the first option whose label does not match the currently-active workspace.
  const target = workspaceOptions.filter({ hasNotText: activeWorkspaceName }).first();

  // Grab only the workspace name span (first <span> inside the <li>); the second
  // span, if present, is a role chip ("owner", "member") and is NOT shown in the
  // switcher button label.
  const targetName = (await target.locator("span").first().innerText()).trim();
  await target.click();

  // After the tenant switch API call resolves, the switcher button label updates
  // to the newly-active workspace name.
  await expect(switcher).toHaveText(new RegExp(targetName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

  // Navigate to the Containers list and confirm it loaded under the new tenant
  // (no "failed to load" or "unauthorized" error banner — verifies data re-scope).
  await page.getByRole("link", { name: "Containers" }).click();
  await expect(page).toHaveURL(/\/containers?$/);
  await expect(page.getByText(/failed to load|unauthorized/i)).toHaveCount(0);
});
