import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Locale } from "@/i18n/config";
import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { AiMode, DocumentOut, MetaOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { DocumentFacts } from "./document-facts";
import { documentFixture, readyDocumentFixture } from "./test-fixtures";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const ANALYSED = readyDocumentFixture(1, { difficulty: "medium", estimated_study_minutes: 25 });
/**
 * A file the live model could not analyse: the built-in analysis stood in, and a real model
 * embedded its passages.
 */
const FELL_BACK: DocumentOut = { ...ANALYSED, embedding_model: "text-embedding-3-small" };

function metaIn(mode: AiMode): MetaOut {
  return {
    max_upload_bytes: 20_971_520,
    allowed_extensions: [".pdf", ".md", ".txt"],
    max_pdf_pages: 500,
    max_active_documents_per_user: 10,
    max_storage_bytes_per_user: 1_073_741_824,
    ai:
      mode === "offline"
        ? { mode, chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" }
        : { mode, chat_model: "gpt-5.4-mini", embedding_model: "text-embedding-3-small" },
  };
}

function renderFacts(
  document: DocumentOut,
  { locale = "en", mode = "offline" }: { locale?: Locale; mode?: AiMode } = {},
) {
  apiFetchMock.mockResolvedValue(metaIn(mode));
  return renderWithIntl(<DocumentFacts document={document} />, { locale });
}

/** The facts as [term, value] pairs, in the order they are listed. */
function rows(): Array<[string, string]> {
  const list = document.querySelector("dl");
  if (!list) {
    throw new Error("No facts are listed.");
  }
  return Array.from(list.querySelectorAll("dt")).map((term) => [
    term.textContent ?? "",
    term.nextElementSibling?.textContent ?? "",
  ]);
}

function valueOf(term: string): string | undefined {
  return rows().find(([label]) => label === term)?.[1];
}

describe("DocumentFacts", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("lists every fact of a processed document, in order, under its own heading", async () => {
    renderFacts(ANALYSED);

    await screen.findByText("Offline analysis");
    expect(screen.getByRole("region", { name: "Details" })).toContainElement(
      document.querySelector("dl"),
    );
    expect(rows()).toEqual([
      ["Difficulty", "Medium"],
      ["Estimated study time", "25 minutes"],
      ["Pages", "12"],
      ["Words", "3,412"],
      ["Fragments", "9"],
      ["Processing time", "1.8 sec"],
      ["Analysed with", "Offline analysis"],
    ]);
  });

  it("rules the facts as rows of one description list", async () => {
    renderFacts(ANALYSED);

    await screen.findByText("Offline analysis");
    const list = document.querySelector("dl");
    expect(list).toHaveClass("divide-y");
    expect(list?.querySelectorAll("dd")).toHaveLength(7);
  });

  it("shows nothing while no fact is known", () => {
    const { container } = renderFacts(documentFixture(1, { status: "processing" }));

    expect(container).toBeEmptyDOMElement();
  });

  it("leaves out the facts that are not known yet", async () => {
    renderFacts(
      documentFixture(1, {
        status: "indexing",
        content_type: "text/markdown",
        difficulty: "easy",
        estimated_study_minutes: 4,
        word_count: 812,
        analysis_model: "mock-heuristic-v1",
      }),
    );

    await screen.findByText("Offline analysis");
    expect(rows().map(([term]) => term)).toEqual([
      "Difficulty",
      "Estimated study time",
      "Words",
      "Analysed with",
    ]);
  });

  it.each([
    ["easy", "Easy", "Низкая"],
    ["medium", "Medium", "Средняя"],
    ["hard", "Hard", "Высокая"],
  ] as const)("names the %s difficulty", async (difficulty, english, russian) => {
    const { unmount } = renderFacts({ ...ANALYSED, difficulty });
    await screen.findByText("Offline analysis");
    expect(valueOf("Difficulty")).toBe(english);
    unmount();

    renderFacts({ ...ANALYSED, difficulty }, { locale: "ru" });
    await screen.findByText("Офлайн-анализ");
    expect(valueOf("Сложность")).toBe(russian);
  });

  it.each([
    [1, "1 minute"],
    [45, "45 minutes"],
    [60, "1 hour"],
    [100, "1 hour 40 minutes"],
    [121, "2 hours 1 minute"],
    [180, "3 hours"],
  ])("words a study time of %i minutes", async (minutes, expected) => {
    renderFacts({ ...ANALYSED, estimated_study_minutes: minutes });

    await screen.findByText("Offline analysis");
    expect(valueOf("Estimated study time")).toBe(expected);
  });

  it.each([
    [1, "1 минута"],
    [3, "3 минуты"],
    [5, "5 минут"],
    [21, "21 минута"],
    [60, "1 час"],
    [125, "2 часа 5 минут"],
    [300, "5 часов"],
    [1441, "24 часа 1 минута"],
  ])("words a study time of %i minutes in Russian", async (minutes, expected) => {
    renderFacts({ ...ANALYSED, estimated_study_minutes: minutes }, { locale: "ru" });

    await screen.findByText("Офлайн-анализ");
    expect(valueOf("Примерное время изучения")).toBe(expected);
  });

  it("says a model that could not analyse the file was replaced by the basic analysis", async () => {
    renderFacts(FELL_BACK, { mode: "live" });

    expect(
      await screen.findByText("Basic analysis (the AI model could not analyse this file)"),
    ).toBeInTheDocument();
  });

  it("names the basic analysis while the file is still being prepared for search", async () => {
    renderFacts(
      {
        ...FELL_BACK,
        status: "indexing",
        chunk_count: null,
        embedding_model: null,
        processing_ms: null,
        processed_at: null,
      },
      { mode: "live" },
    );

    expect(
      await screen.findByText("Basic analysis (the AI model could not analyse this file)"),
    ).toBeInTheDocument();
  });

  it("keeps an offline analysis offline once a model is in use", async () => {
    renderFacts(ANALYSED, { mode: "live" });

    await screen.findByText("Offline analysis");
    expect(valueOf("Analysed with")).toBe("Offline analysis");
  });

  it("names the model that analysed the file", async () => {
    renderFacts({ ...ANALYSED, analysis_model: "gpt-5.4-mini" }, { mode: "live" });

    await screen.findByText("gpt-5.4-mini");
    expect(valueOf("Analysed with")).toBe("gpt-5.4-mini");
  });

  it("still names a model that analysed the file before the server went offline", async () => {
    renderFacts({ ...ANALYSED, analysis_model: "gpt-5.4-mini" });

    expect(await screen.findByText("gpt-5.4-mini")).toBeInTheDocument();
  });

  it("leaves out the analyser until the AI mode is known", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));
    renderWithIntl(<DocumentFacts document={ANALYSED} />);

    expect(rows().map(([term]) => term)).not.toContain("Analysed with");
    expect(rows()).toHaveLength(6);
  });

  it("leaves out the analyser when the AI mode cannot be loaded", async () => {
    apiFetchMock.mockRejectedValue(new ApiError({ status: 503, code: "http_error", message: "x" }));
    renderWithIntl(<DocumentFacts document={ANALYSED} />);

    await vi.waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith("/meta"));
    expect(rows().map(([term]) => term)).not.toContain("Analysed with");
  });

  it("speaks Russian", async () => {
    renderFacts(ANALYSED, { locale: "ru" });

    await screen.findByText("Офлайн-анализ");
    expect(screen.getByRole("region", { name: "Подробности" })).toBeInTheDocument();
    expect(rows()).toEqual([
      ["Сложность", "Средняя"],
      ["Примерное время изучения", "25 минут"],
      ["Страниц", "12"],
      // The no-break space that groups the digits stays as it is in the text content.
      ["Слов", "3 412"],
      ["Фрагментов", "9"],
      ["Время обработки", "1,8 с"],
      ["Способ анализа", "Офлайн-анализ"],
    ]);
  });

  it("explains the basic analysis in Russian", async () => {
    renderFacts(FELL_BACK, { locale: "ru", mode: "live" });

    expect(
      await screen.findByText("Базовый анализ (модель ИИ не смогла проанализировать этот файл)"),
    ).toBeInTheDocument();
  });

  it("keeps an offline analysis offline in Russian once a model is in use", async () => {
    renderFacts(ANALYSED, { locale: "ru", mode: "live" });

    await screen.findByText("Офлайн-анализ");
    expect(valueOf("Способ анализа")).toBe("Офлайн-анализ");
  });
});
