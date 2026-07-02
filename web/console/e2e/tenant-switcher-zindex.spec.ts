import { test, expect, requireStack, login } from "./helpers";

// Regression: the tenant switcher dropdown must render ABOVE page content.
//
// Root cause it guards against: the switcher menu lives inside the header's
// `.fc-ctxbar-center` cluster, which is a stacking context (it uses a centering
// `transform`). The scrolling page content (`.fc-scroll`) is a later sibling of
// the header, and cards like the dashboard hero tile form their own stacking
// context via a transform animation. Two `z-index:auto` contexts paint in DOM
// order, so without a stacking context on the header the (later) page content
// paints OVER the dropdown — regardless of the menu's own `z-index`.
const ADMIN = { email: process.env.E2E_ADMIN_EMAIL ?? "e2e-admin@x.io", pw: process.env.E2E_ADMIN_PW ?? "ChangeMe!1" };

test.beforeEach(async ({ page }) => { await requireStack(page); });

test("tenant switcher dropdown paints above dashboard content", async ({ page }) => {
  await login(page, ADMIN.email, ADMIN.pw);
  if (page.url().includes("/change-password")) {
    await page.getByLabel("Current password").fill(ADMIN.pw);
    await page.getByLabel("New password").fill("NewPass!234");
    await page.getByRole("button", { name: "Update password" }).click();
    ADMIN.pw = "NewPass!234";
  }

  // Land on the dashboard, which renders the transformed hero tile under the menu.
  await page.goto("/");
  const hero = page.locator(".tile-hero");
  if ((await hero.count()) === 0) test.skip(true, "dashboard hero tile not present");
  await expect(hero.first()).toBeVisible();

  // Open the switcher.
  const switcher = page.locator('button[aria-haspopup="listbox"]');
  await switcher.click();
  const menu = page.locator(".tenant-switcher .dd-menu");
  await expect(menu).toBeVisible();

  // At a point inside the menu that overlaps the page content below the header,
  // the topmost element must be the menu (or one of its descendants) — not a
  // page tile painting over it.
  const menuIsOnTop = await menu.evaluate((el) => {
    const r = el.getBoundingClientRect();
    // sample near the bottom of the menu, well past the ~52px header
    const x = r.left + r.width / 2;
    const y = r.bottom - Math.min(24, r.height * 0.15);
    const top = document.elementsFromPoint(x, y)[0];
    return el === top || el.contains(top);
  });
  expect(menuIsOnTop).toBe(true);
});
