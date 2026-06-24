import { test as base, expect, type Page } from "@playwright/test";

// Skip the whole e2e file cleanly when the stack isn't reachable.
export const test = base.extend({});
export { expect };

export async function requireStack(page: Page) {
  try {
    const res = await page.request.get("/v1/auth/me");
    // any HTTP response (even 401) proves the stack is up
    if (!res) test.skip(true, "compose stack not reachable");
  } catch {
    test.skip(true, "compose stack not reachable — run `docker compose -f deploy/docker-compose.yml up -d`");
  }
}

export async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}
