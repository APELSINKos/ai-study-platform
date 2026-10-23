import { expect, type Page } from "@playwright/test";

export interface Account {
  displayName: string;
  email: string;
  password: string;
}

/** An account no earlier run has registered; `suite` names the suite in its address. */
export function newAccount(suite: string, displayName: string): Account {
  const random = Math.random().toString(36).slice(2, 8);
  return {
    displayName,
    email: `e2e-${suite}-${Date.now()}-${random}@example.com`,
    password: "correct horse battery staple",
  };
}

/** Registers the account through the form, as a visitor does, and waits for the dashboard. */
export async function registerThroughUi(page: Page, account: Account): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Name").fill(account.displayName);
  await page.getByLabel("Email").fill(account.email);
  await page.getByLabel("Password").fill(account.password);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
}
