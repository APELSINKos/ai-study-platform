import { request } from "@playwright/test";

import { baseURL } from "../playwright.config";

const WARMUP_TIMEOUT_MS = 30_000;
// Without this hint the proxy redirects the signed-in pages to /login and they never compile.
const SESSION_HINT_COOKIE = "recall_csrf=warm-up";

// next dev compiles each page on first request; with several workers hitting a cold
// server in parallel, the slowest compile can exceed a test's timeout. Requesting every
// page once here, before any test runs, avoids that.
export default async function globalSetup(): Promise<void> {
  const context = await request.newContext({ baseURL, timeout: WARMUP_TIMEOUT_MS });
  await context.get("/");
  await context.get("/status");
  await context.get("/login");
  await context.get("/register");
  await context.get("/dashboard", { headers: { cookie: SESSION_HINT_COOKIE } });
  await context.get("/workspaces", { headers: { cookie: SESSION_HINT_COOKIE } });
  await context.dispose();
}
