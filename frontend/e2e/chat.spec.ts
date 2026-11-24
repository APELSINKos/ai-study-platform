import { expect, test, type Page } from "@playwright/test";

import { newAccount, registerThroughUi } from "./account";

// The worker needs well under a second for these files; the list asks again every 2 s.
const PROCESSING_TIMEOUT_MS = 20_000;
const BUILT_IN_MODEL = /^mock-/;
const CSRF_COOKIE = "recall_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const WORKSPACE_URL = /\/workspaces\/[0-9a-f-]{36}$/;
const CHAT_SESSION_URL = /\/chat\?session=[0-9a-f-]{36}$/;
const PASSAGE_URL = /\/documents\/[0-9a-f-]{36}\?fragment=\d+$/;

const ACCOUNT = newAccount("chat", "E2E Chat Reader");
const WORKSPACE_NAME = "Memory and recall";

const NOTES = {
  filename: "forgetting-curve.md",
  title: "The forgetting curve",
  firstSentence: "Without review, most of a lecture is forgotten within a week.",
  secondSentence: "Each review makes the next loss slower than the one before.",
};

const GROUNDED_QUESTION = "How does review slow down forgetting a lecture?";
const UNRELATED_QUESTION = "What is the recipe for chocolate xylophone soup?";
const RENAMED_TITLE = "Forgetting curve review";
const INSUFFICIENT_NO_PASSAGES =
  "No relevant passages were found in the selected materials, so Recall did not guess. Try rephrasing your question or widening the document scope.";

interface UploadFile {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

function notesFile(): UploadFile {
  const text = [
    `# ${NOTES.title}`,
    NOTES.firstSentence,
    "## Spaced repetition",
    NOTES.secondSentence,
  ].join("\n\n");
  return { name: NOTES.filename, mimeType: "text/markdown", buffer: Buffer.from(`${text}\n`) };
}

async function chooseFiles(page: Page, files: UploadFile[]): Promise<void> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Upload files" }).click();
  await (await chooser).setFiles(files);
}

function conversationTurns(page: Page) {
  return page.getByRole("list", { name: "Conversation" }).locator("> li");
}

async function askQuestion(page: Page, question: string): Promise<void> {
  await page.getByLabel("Your question").fill(question);
  await page.getByRole("button", { name: "Send" }).click();
}

/** Deletes a workspace the way the web app does, and fails when the workspace is left behind. */
async function deleteWorkspace(page: Page, id: string): Promise<void> {
  const cookies = await page.context().cookies();
  const csrf = cookies.find((cookie) => cookie.name === CSRF_COOKIE);
  if (csrf === undefined) {
    throw new Error(`Workspace ${id} is left behind: the session has no ${CSRF_COOKIE} cookie.`);
  }
  const response = await page.request.delete(`/api/v1/workspaces/${id}`, {
    headers: { [CSRF_HEADER]: csrf.value },
  });
  expect(response.status(), `Workspace ${id} is left behind`).toBe(204);
}

// Registration is rate-limited per IP, so this suite registers one account and walks one
// workspace through grounded chat, citations, passage deep links, refusal, rename and deletion.
test.describe.serial("grounded chat and citations", () => {
  let page: Page;
  let workspaceId: string | null = null;
  let sessionUrl: string | null = null;

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
  });

  test.afterAll(async () => {
    try {
      if (workspaceId !== null) {
        await deleteWorkspace(page, workspaceId);
      }
    } finally {
      await page.close();
    }
  });

  test("runs against the built-in offline models", async () => {
    const response = await page.request.get("/api/v1/meta");
    expect(response.ok()).toBe(true);
    const meta: unknown = await response.json();

    expect(meta, "Run the stack without OPENAI_API_KEY and EMBEDDING_API_KEY").toMatchObject({
      ai: {
        mode: "offline",
        chat_model: expect.stringMatching(BUILT_IN_MODEL),
        embedding_model: expect.stringMatching(BUILT_IN_MODEL),
      },
    });
  });

  test("registers, creates a workspace and uploads notes until ready", async () => {
    await registerThroughUi(page, ACCOUNT);

    await page.getByRole("link", { name: "New workspace" }).click();
    await page.getByLabel("Name").fill(WORKSPACE_NAME);
    await page.getByRole("button", { name: "Create workspace" }).click();

    await expect(page).toHaveURL(WORKSPACE_URL);
    workspaceId = new URL(page.url()).pathname.split("/").pop() ?? null;
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(WORKSPACE_NAME);

    await chooseFiles(page, [notesFile()]);
    await expect(page.getByText("The file is ready.")).toBeVisible({
      timeout: PROCESSING_TIMEOUT_MS,
    });
    await expect(
      page
        .getByRole("list", { name: "Documents in this workspace" })
        .getByRole("listitem")
        .filter({ hasText: NOTES.title }),
    ).toContainText("Ready");
  });

  test("opens chat from the workspace and starts a session", async () => {
    await page.getByRole("link", { name: "Ask in chat" }).click();

    await expect(page).toHaveURL(new RegExp(`/chat\\?workspace=${workspaceId}$`));
    await page.getByRole("button", { name: "Start chat" }).click();

    await expect(page).toHaveURL(CHAT_SESSION_URL);
    sessionUrl = page.url();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("New chat");
  });

  test("answers with inline citations, previews the source and opens the passage", async () => {
    await askQuestion(page, GROUNDED_QUESTION);

    const turns = conversationTurns(page);
    await expect(turns).toHaveCount(2);
    await expect(turns.nth(0)).toContainText(GROUNDED_QUESTION);

    const answerTurn = turns.nth(1);
    const sourcesList = answerTurn.getByRole("list", { name: "Sources" });
    await expect(sourcesList).toBeVisible();
    await expect(sourcesList).toContainText(NOTES.title);

    const inlineCitation = answerTurn
      .getByRole("button", { name: `Source 1: ${NOTES.title}` })
      .first();
    await expect(inlineCitation).toBeVisible();
    await inlineCitation.click();

    const popover = page.getByRole("dialog");
    await expect(popover).toBeVisible();
    await expect(popover).toContainText(NOTES.title);
    await expect(popover.locator("blockquote")).toContainText(
      new RegExp(`${NOTES.firstSentence}|${NOTES.secondSentence}`),
    );
    const openPassageLink = popover.getByRole("link", { name: "Open passage" });
    await expect(openPassageLink).toBeVisible();
    await openPassageLink.click();

    await expect(page).toHaveURL(PASSAGE_URL);
    const opened = page
      .getByRole("region", { name: "Passages" })
      .getByRole("listitem")
      .filter({ hasText: "The passage you opened" });
    await expect(opened).toBeVisible();
    await expect(opened).toBeFocused();
  });

  test("keeps prior turns on return and reports insufficient context for unrelated questions", async () => {
    if (sessionUrl === null) {
      throw new Error("Expected session URL to be captured before returning to chat.");
    }
    await page.goBack();
    await expect(page).toHaveURL(sessionUrl);

    const turns = conversationTurns(page);
    await expect(turns).toHaveCount(2);
    await expect(turns.nth(0)).toContainText(GROUNDED_QUESTION);
    await expect(turns.nth(1).getByRole("list", { name: "Sources" })).toBeVisible();

    await askQuestion(page, UNRELATED_QUESTION);

    await expect(turns).toHaveCount(4);
    await expect(turns.nth(2)).toContainText(UNRELATED_QUESTION);
    const refusalTurn = turns.nth(3);
    await expect(refusalTurn).toContainText(INSUFFICIENT_NO_PASSAGES);
    await expect(refusalTurn.getByRole("list", { name: "Sources" })).toHaveCount(0);
    await expect(refusalTurn.getByRole("button", { name: /^Source \d+:/ })).toHaveCount(0);
  });

  test("renames the session inline, persists the title and deletes the session cleanly", async () => {
    await page.getByRole("button", { name: "Rename" }).click();
    await page.getByLabel("Chat title").fill(RENAMED_TITLE);
    await page.getByRole("button", { name: "Save" }).click();

    await expect(page.getByRole("heading", { level: 1 })).toHaveText(RENAMED_TITLE);

    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(RENAMED_TITLE);

    await page.getByRole("button", { name: "Delete" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete chat" }).click();

    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Chat");

    // Deleting replaced the session history entry, so Back does not return to the deleted session.
    await page.goBack();
    await expect(page).not.toHaveURL(CHAT_SESSION_URL);
  });
});
