import { expect, test } from "@playwright/test";

test("shows the live status of the backend", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Read it once. Recall it on exam day.",
  );
  await expect(page.getByRole("status")).toHaveText("Everything is running.");
});

test("switches the interface to Russian and remembers the choice", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "RU" }).click();

  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    "Прочитайте один раз. Вспомните на экзамене.",
  );
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "ru");
});

test("switches to the dark theme", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "Dark" }).click();

  await expect(page.locator("html")).toHaveClass(/dark/);
});
