import { expect, test, type Page } from "@playwright/test";

const REGISTER_ENDPOINT = "/api/v1/auth/register";

function uniqueEmail(): string {
  const random = Math.random().toString(36).slice(2, 8);
  return `e2e-${Date.now()}-${random}@example.com`;
}

const CREDENTIALS = {
  displayName: "E2E Tester",
  email: uniqueEmail(),
  password: "correct horse battery staple",
  wrongPassword: "not the right password",
};

// Registration is rate-limited per IP, so this suite creates exactly one
// account and reuses it for every step of the lifecycle below.
test.describe.serial("account lifecycle", () => {
  let page: Page;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
  });

  test.afterAll(async () => {
    await page.close();
  });

  test("registers through the UI and lands on the dashboard", async () => {
    await page.goto("/register");
    await page.getByLabel("Name").fill(CREDENTIALS.displayName);
    await page.getByLabel("Email").fill(CREDENTIALS.email);
    await page.getByLabel("Password").fill(CREDENTIALS.password);
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(CREDENTIALS.displayName);
  });

  test("signs out from the user menu", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();

    await expect(page).toHaveURL(/\/login$/);
  });

  test("redirects a signed-out visit to the dashboard through login", async () => {
    await page.goto("/dashboard");

    await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
  });

  test("rejects the wrong password with an alert", async () => {
    await page.getByLabel("Email").fill(CREDENTIALS.email);
    await page.getByLabel("Password").fill(CREDENTIALS.wrongPassword);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText("Incorrect email or password.")).toHaveAttribute("role", "alert");
  });

  test("signs in with the right password and returns to the dashboard", async () => {
    await page.getByLabel("Password").fill(CREDENTIALS.password);
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test("refreshes the session once the access cookie expires", async () => {
    await page.context().clearCookies({ name: "recall_access" });
    await page.reload();

    await expect(page.getByRole("heading", { level: 1 })).toContainText(CREDENTIALS.displayName);
    const cookies = await page.context().cookies();
    expect(cookies.some((cookie) => cookie.name === "recall_access")).toBe(true);
  });
});

test("shows the login page in Russian after switching from the header", async ({ page }) => {
  await page.goto("/login");

  await page.getByRole("banner").getByRole("button", { name: "RU" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Вход");
  await expect(page.getByLabel("Пароль")).toBeVisible();
  await expect(page.getByText("Создать аккаунт")).toBeVisible();
});

test("rejects an empty registration form without contacting the API", async ({ page }) => {
  let registerRequests = 0;
  page.on("request", (request) => {
    if (request.url().includes(REGISTER_ENDPOINT)) {
      registerRequests += 1;
    }
  });

  await page.goto("/register");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByText("Enter your name.")).toBeVisible();
  await expect(page.getByText("Enter your email address.")).toBeVisible();
  await expect(page.getByText("Password must be at least 10 characters.")).toBeVisible();
  expect(registerRequests).toBe(0);
});
