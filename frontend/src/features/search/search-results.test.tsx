import { screen, within } from "@testing-library/react";
import { useTranslations } from "next-intl";
import { describe, expect, it } from "vitest";

import type { Locale } from "@/i18n/config";
import type { SearchHit, SearchResults } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { ResultList, SearchNotes } from "./search-results";
import { searchHitFixture, searchResultsFixture } from "./test-fixtures";

const DOCUMENT_ID = searchHitFixture(1).document_id;

function renderList(hits: SearchHit[], locale: Locale = "en") {
  return renderWithIntl(<ResultList hits={hits} />, { locale });
}

function renderNotes(overrides: Partial<SearchResults>, locale: Locale = "en") {
  return renderWithIntl(<SearchNotes results={searchResultsFixture(2, overrides)} />, { locale });
}

function rows(name = "Search results"): HTMLElement[] {
  return within(screen.getByRole("list", { name })).getAllByRole("listitem");
}

function notes(): string[] {
  return screen.queryAllByRole("paragraph").map((note) => note.textContent ?? "");
}

describe("ResultList", () => {
  it("lists the passages in the order found, each with its document, headings, pages and words", () => {
    renderList([
      searchHitFixture(1, {
        document_title: "Plant biology",
        heading: "Photosynthesis › Light reactions",
        page_start: 4,
        page_end: 5,
      }),
      searchHitFixture(2, { page_start: 7, page_end: 7 }),
    ]);

    expect(screen.getByRole("list", { name: "Search results" }).tagName).toBe("OL");
    const [first, second] = rows();
    expect(first).toHaveTextContent("Plant biology");
    expect(first).toHaveTextContent("Photosynthesis › Light reactions");
    expect(first).toHaveTextContent("Pages 4–5");
    expect(first).toHaveTextContent("Chloroplasts turn light into the energy of sugar.");
    expect(second).toHaveTextContent("Lecture 1");
    expect(second).toHaveTextContent("Page 7");
  });

  it("opens each passage at its place in its document", () => {
    renderList([searchHitFixture(1), searchHitFixture(2)]);

    const [first, second] = rows();
    expect(within(first ?? document.body).getByRole("link")).toHaveAttribute(
      "href",
      `/documents/${DOCUMENT_ID}?fragment=11`,
    );
    expect(within(second ?? document.body).getByRole("link")).toHaveAttribute(
      "href",
      `/documents/${DOCUMENT_ID}?fragment=12`,
    );
  });

  it("gives passages of one document distinct link names", () => {
    renderList([
      searchHitFixture(1, { page_start: 3, page_end: 3 }),
      // On the same page as the first.
      searchHitFixture(2, { page_start: 3, page_end: 3 }),
      searchHitFixture(3, { heading: "Glycolysis", page_start: null, page_end: null }),
      searchHitFixture(4, { page_start: null, page_end: null }),
    ]);

    const names = [
      "Lecture 1, Page 3, Passage 12",
      "Lecture 1, Page 3, Passage 13",
      "Lecture 1, Glycolysis, Passage 14",
      "Lecture 1, Passage 15",
    ];
    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(names.length);
    names.forEach((name, index) => {
      expect(screen.getByRole("link", { name })).toBe(links[index]);
    });
    // Only the title shows; the rest is for the list of links a screen reader offers.
    for (const link of links) {
      expect(link).toHaveTextContent(/^Lecture 1$/);
    }
  });

  it("leaves out the headings and the pages a passage does not have", () => {
    renderList([searchHitFixture(1, { heading: null, page_start: null, page_end: null })]);

    const [row] = rows();
    expect(row?.querySelectorAll("p")).toHaveLength(1);
    expect(row).toHaveTextContent("Chloroplasts turn light into the energy of sugar.");
  });

  it("shows the title, headings and words as plain text", () => {
    const markup = "<img src=x onerror=alert(1)>";
    renderList([
      searchHitFixture(1, {
        document_title: `${markup} notes`,
        heading: `${markup} heading`,
        snippet: [
          { text: `${markup} before `, highlighted: false },
          { text: markup, highlighted: true },
        ],
      }),
    ]);

    const [row] = rows();
    expect(row).toHaveTextContent(`${markup} notes`);
    expect(within(row ?? document.body).getByText(`${markup} heading`)).toBeVisible();
    expect(row).toHaveTextContent(`${markup} before ${markup}`);
    expect(document.querySelector("img")).toBeNull();
  });

  it("lists nothing when no passage matches", () => {
    renderList([]);

    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("speaks Russian", () => {
    renderList(
      [
        searchHitFixture(1, { page_start: 4, page_end: 5 }),
        searchHitFixture(2, { page_start: 7, page_end: 7 }),
      ],
      "ru",
    );

    const [first, second] = rows("Результаты поиска");
    expect(first).toHaveTextContent("Страницы 4–5");
    expect(second).toHaveTextContent("Страница 7");
    expect(screen.getByRole("link", { name: "Lecture 1, Страница 7, Фрагмент 13" })).toBeVisible();
  });
});

describe("SearchNotes", () => {
  it("says nothing when every ready file was searched in full", () => {
    renderNotes({});

    expect(notes()).toEqual([]);
  });

  it("says no file is ready to be searched", () => {
    renderNotes({ results: [], searched_document_count: 0, semantic_available: false });

    expect(notes()).toEqual(["No file in this workspace is ready to be searched."]);
  });

  it("counts the files still being processed", () => {
    renderNotes({ pending_document_count: 3 });

    expect(notes()).toEqual([
      "3 files are still being processed — search again once they are ready.",
    ]);
  });

  it("counts the files indexed with another model", () => {
    renderNotes({ searched_document_count: 3, stale_document_count: 1 });

    expect(notes()).toEqual([
      "1 file was indexed with another model: until it is re-indexed, only its words are searched.",
    ]);
  });

  it("says only the words were looked for when the embeddings were not compared", () => {
    renderNotes({ semantic_available: false });

    expect(notes()).toEqual(["Only the words of your query were looked for."]);
  });

  it("leaves words only to the note on other models when no ready file has the current one", () => {
    renderNotes({ semantic_available: false, searched_document_count: 2, stale_document_count: 2 });

    expect(notes()).toEqual([
      "2 files were indexed with another model: until they are re-indexed, only their words are searched.",
    ]);
  });

  it("gives every note that applies, in a fixed order", () => {
    renderNotes({
      results: [],
      semantic_available: false,
      searched_document_count: 0,
      pending_document_count: 1,
    });

    expect(notes()).toEqual([
      "No file in this workspace is ready to be searched.",
      "1 file is still being processed — search again once it is ready.",
    ]);
  });

  it("speaks Russian", () => {
    renderNotes(
      {
        semantic_available: false,
        searched_document_count: 3,
        stale_document_count: 1,
        pending_document_count: 2,
      },
      "ru",
    );

    expect(notes()).toEqual([
      "2 файла ещё обрабатываются — повторите поиск, когда обработка закончится.",
      "1 файл проиндексирован другой моделью: до переиндексации в таких файлах ищутся только слова.",
      "Искались только слова запроса.",
    ]);
  });

  it("says no file is ready in Russian", () => {
    renderNotes({ results: [], searched_document_count: 0, semantic_available: false }, "ru");

    expect(notes()).toEqual(["В пространстве нет файлов, готовых к поиску."]);
  });
});

type CountMessage = "status.found" | "status.closest" | "notes.pending" | "notes.stale";

function CountProbe({ message, count }: { message: CountMessage; count: number }) {
  const t = useTranslations("Search");
  return <p>{t(message, { count })}</p>;
}

function counted(message: CountMessage, count: number, locale: Locale): string {
  const { unmount } = renderWithIntl(<CountProbe message={message} count={count} />, { locale });
  const text = screen.getByRole("paragraph").textContent ?? "";
  unmount();
  return text;
}

describe("count messages", () => {
  it.each([
    ["status.found", 0, "No passages match."],
    ["status.found", 1, "1 passage matches."],
    ["status.found", 2, "2 passages match."],
    ["status.closest", 1, "The closest passage."],
    ["status.closest", 10, "The 10 closest passages."],
    ["notes.pending", 1, "1 file is still being processed — search again once it is ready."],
    ["notes.pending", 2, "2 files are still being processed — search again once they are ready."],
    [
      "notes.stale",
      2,
      "2 files were indexed with another model: until they are re-indexed, only their words are searched.",
    ],
  ] as const)("words %s for %i in English", (message, count, expected) => {
    expect(counted(message, count, "en")).toBe(expected);
  });

  it.each([
    ["status.found", 0, "Подходящих фрагментов нет."],
    ["status.found", 1, "Запросу соответствует 1 фрагмент."],
    ["status.found", 2, "Запросу соответствуют 2 фрагмента."],
    ["status.found", 5, "Запросу соответствуют 5 фрагментов."],
    ["status.found", 11, "Запросу соответствуют 11 фрагментов."],
    ["status.found", 21, "Запросу соответствует 21 фрагмент."],
    ["status.closest", 1, "1 ближайший к запросу фрагмент."],
    ["status.closest", 2, "2 ближайших к запросу фрагмента."],
    ["status.closest", 5, "5 ближайших к запросу фрагментов."],
    ["status.closest", 11, "11 ближайших к запросу фрагментов."],
    ["status.closest", 21, "21 ближайший к запросу фрагмент."],
    [
      "notes.pending",
      1,
      "1 файл ещё обрабатывается — повторите поиск, когда обработка закончится.",
    ],
    [
      "notes.pending",
      2,
      "2 файла ещё обрабатываются — повторите поиск, когда обработка закончится.",
    ],
    [
      "notes.pending",
      5,
      "5 файлов ещё обрабатываются — повторите поиск, когда обработка закончится.",
    ],
    [
      "notes.pending",
      11,
      "11 файлов ещё обрабатываются — повторите поиск, когда обработка закончится.",
    ],
    [
      "notes.pending",
      21,
      "21 файл ещё обрабатывается — повторите поиск, когда обработка закончится.",
    ],
    [
      "notes.stale",
      1,
      "1 файл проиндексирован другой моделью: до переиндексации в таких файлах ищутся только слова.",
    ],
    [
      "notes.stale",
      2,
      "2 файла проиндексированы другой моделью: до переиндексации в таких файлах ищутся только слова.",
    ],
    [
      "notes.stale",
      5,
      "5 файлов проиндексированы другой моделью: до переиндексации в таких файлах ищутся только слова.",
    ],
    [
      "notes.stale",
      11,
      "11 файлов проиндексированы другой моделью: до переиндексации в таких файлах ищутся только слова.",
    ],
    [
      "notes.stale",
      21,
      "21 файл проиндексирован другой моделью: до переиндексации в таких файлах ищутся только слова.",
    ],
  ] as const)("words %s for %i in Russian", (message, count, expected) => {
    expect(counted(message, count, "ru")).toBe(expected);
  });
});
