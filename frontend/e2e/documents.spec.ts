import { expect, test, type Page, type Request } from "@playwright/test";

import { newAccount, registerThroughUi } from "./account";

const MIB = 1024 * 1024;
const UPLOAD_LIMIT_BYTES = 20 * MIB;
// Holds far more text than one document may have, yet passes the upload limit.
const LONG_FILE_BYTES = 12 * MIB;
// The worker needs well under a second for these files; the list asks again every 2 s.
const PROCESSING_TIMEOUT_MS = 20_000;
const BUILT_IN_MODEL = /^mock-/;
const CSRF_COOKIE = "recall_csrf";
const CSRF_HEADER = "X-CSRF-Token";
const WORKSPACE_URL = /\/workspaces\/[0-9a-f-]{36}$/;
const DOCUMENT_URL = /\/documents\/[0-9a-f-]{36}$/;
const PASSAGE_URL = /\/documents\/[0-9a-f-]{36}\?fragment=\d+$/;
// A word of the notes, and one that shares no word, nor the beginning of one, with them: the
// built-in embeddings compare words and their beginnings.
const FOUND_WORD = "slower";
const MISSING_WORD = "xylophone";
const FOUND_WORD_URL = /\/workspaces\/[0-9a-f-]{36}\?q=slower$/;

const ACCOUNT = newAccount("documents", "E2E Reader");
const WORKSPACE_NAME = "Memory and learning";

// The offline analysis titles a file after its first heading and sums it up with its first
// sentences; each section of the file becomes a fragment of its own.
const NOTES = {
  filename: "forgetting-curve.md",
  title: "The forgetting curve",
  firstSentence: "Without review, most of a lecture is forgotten within a week.",
  secondSentence: "Each review makes the next loss slower than the one before.",
};

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

/** A Markdown file of exactly `bytes` bytes: one line written over and over. */
function repeatedLineFile(name: string, bytes: number): UploadFile {
  const buffer = Buffer.alloc(bytes, "Spaced reviews slow down forgetting.\n");
  return { name, mimeType: "text/markdown", buffer };
}

/** Picks files through Upload files, as a user does; the click waits until it is enabled. */
async function chooseFiles(page: Page, files: UploadFile[]): Promise<void> {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Upload files" }).click();
  await (await chooser).setFiles(files);
}

function uploadResults(page: Page) {
  return page.getByRole("list", { name: "Upload results" });
}

function documentRow(page: Page, name: string) {
  return page
    .getByRole("list", { name: "Documents in this workspace" })
    .getByRole("listitem")
    .filter({ hasText: name });
}

function searchSection(page: Page) {
  return page.getByRole("region", { name: "Search" });
}

async function search(page: Page, words: string): Promise<void> {
  const section = searchSection(page);
  await section.getByRole("searchbox", { name: "Words to look for" }).fill(words);
  await section.getByRole("button", { name: "Search", exact: true }).click();
}

/** The results whose snippet marks `word` as a word the query matched. */
function resultsMarking(page: Page, word: string) {
  return searchSection(page)
    .getByRole("list", { name: "Search results" })
    .getByRole("listitem")
    .filter({ has: page.locator("mark", { hasText: word }) });
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

// Registration is rate-limited per IP, so this suite creates exactly one account and walks
// it through one workspace's whole life: uploads, processing, refusals, search and deletion.
test.describe.serial("documents from upload to deletion", () => {
  let page: Page;
  let workspaceId: string | null = null;

  function isUpload(request: Request): boolean {
    return (
      request.method() === "POST" &&
      new URL(request.url()).pathname === `/api/v1/workspaces/${workspaceId}/documents`
    );
  }

  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
  });

  test.afterAll(async () => {
    // The last step clears the id once it has deleted the workspace; after a failed step the
    // workspace and its files are removed here instead.
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

    // "offline" holds as soon as one of the two models is built in. Both must be: no run may
    // pay for a model, and the title and summary below are the built-in analysis's.
    expect(meta, "Run the stack without OPENAI_API_KEY and EMBEDDING_API_KEY").toMatchObject({
      ai: {
        mode: "offline",
        chat_model: expect.stringMatching(BUILT_IN_MODEL),
        embedding_model: expect.stringMatching(BUILT_IN_MODEL),
      },
    });
  });

  test("registers a new account", async () => {
    await registerThroughUi(page, ACCOUNT);
  });

  test("creates a workspace from the dashboard", async () => {
    await page.getByRole("link", { name: "New workspace" }).click();
    await page.getByLabel("Name").fill(WORKSPACE_NAME);
    await page.getByRole("button", { name: "Create workspace" }).click();

    await expect(page).toHaveURL(WORKSPACE_URL);
    workspaceId = new URL(page.url()).pathname.split("/").pop() ?? null;
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(WORKSPACE_NAME);
  });

  test("uploads notes and waits until they are ready", async () => {
    await chooseFiles(page, [notesFile()]);

    await expect(uploadResults(page)).toContainText("Uploaded");
    await expect(page.getByText("The file is ready.")).toBeVisible({
      timeout: PROCESSING_TIMEOUT_MS,
    });
    await expect(documentRow(page, NOTES.title)).toContainText("Ready");
  });

  test("opens the document with its title, summary and fragments", async () => {
    await documentRow(page, NOTES.title).getByRole("link", { name: NOTES.title }).click();

    await expect(page).toHaveURL(DOCUMENT_URL);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(NOTES.title);
    await expect(
      page.getByText(`${NOTES.firstSentence} ${NOTES.secondSentence}`, { exact: true }),
    ).toBeVisible();
    const fragments = page.getByRole("region", { name: "Passages" });
    await expect(fragments.getByRole("listitem").first()).toContainText(NOTES.firstSentence);
  });

  test("turns down the same file again as a duplicate", async () => {
    await page.goBack();
    await expect(page).toHaveURL(WORKSPACE_URL);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(WORKSPACE_NAME);

    await chooseFiles(page, [notesFile()]);

    await expect(uploadResults(page)).toContainText("This file is already in the workspace.");
  });

  test("accepts a 12 MiB file and then fails it for holding too much text", async () => {
    const file = repeatedLineFile("lecture-transcript.md", LONG_FILE_BYTES);
    const uploaded = page.waitForResponse((response) => isUpload(response.request()));

    await chooseFiles(page, [file]);

    expect((await uploaded).status()).toBe(202);
    const row = documentRow(page, file.name);
    await expect(row).toContainText("Failed", { timeout: PROCESSING_TIMEOUT_MS });
    await expect(row).toContainText("The file holds too much text. Split it into smaller files.");
  });

  test("turns down a file over 20 MiB without sending it", async () => {
    let sent = 0;
    const countUploads = (request: Request) => {
      if (isUpload(request)) {
        sent += 1;
      }
    };
    page.on("request", countUploads);

    await chooseFiles(page, [repeatedLineFile("lecture-recording.md", UPLOAD_LIMIT_BYTES + 1)]);

    await expect(uploadResults(page)).toContainText("The file is larger than 20 MB.");
    page.off("request", countUploads);
    expect(sent).toBe(0);
  });

  test("finds a passage of the notes by one of its words, marked in the snippet", async () => {
    await search(page, FOUND_WORD);

    await expect(page).toHaveURL(FOUND_WORD_URL);
    const result = resultsMarking(page, FOUND_WORD);
    await expect(result).toHaveCount(1);
    await expect(result.locator("mark")).toHaveText(FOUND_WORD);
    await expect(result).toContainText(NOTES.title);
  });

  test("opens the document at the passage a result cites, with the focus on it", async () => {
    await resultsMarking(page, FOUND_WORD).getByRole("link").click();

    await expect(page).toHaveURL(PASSAGE_URL);
    const opened = page
      .getByRole("region", { name: "Passages" })
      .getByRole("listitem")
      .filter({ hasText: "The passage you opened" });
    await expect(opened).toBeVisible();
    await expect(opened).toBeFocused();
    await expect(opened).toContainText(NOTES.secondSentence);
  });

  test("comes back to the same search and its results", async () => {
    await page.goBack();

    await expect(page).toHaveURL(FOUND_WORD_URL);
    await expect(
      searchSection(page).getByRole("searchbox", { name: "Words to look for" }),
    ).toHaveValue(FOUND_WORD);
    await expect(resultsMarking(page, FOUND_WORD)).toBeVisible();
  });

  test("says so when no passage matches", async () => {
    await search(page, MISSING_WORD);

    await expect(searchSection(page).getByRole("status")).toHaveText("No passages match.");
    await expect(searchSection(page).getByRole("list", { name: "Search results" })).toHaveCount(0);
  });

  test("deletes the workspace and comes back to an empty list", async () => {
    await page.getByRole("button", { name: "Delete workspace" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Delete workspace" }).click();

    // The app leaves the workspace's page only once the deletion has succeeded.
    await expect(page).toHaveURL(/\/workspaces$/);
    workspaceId = null;
    await expect(
      page.getByText("You have no workspaces yet. Start with the course you are studying now."),
    ).toBeVisible();
  });
});
