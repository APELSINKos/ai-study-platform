import { describe, expect, it } from "vitest";

import {
  acceptAttribute,
  checkFile,
  extensionOf,
  listExtensions,
  type FileRules,
} from "./file-rules";

const MIB = 1024 * 1024;

const RULES: FileRules = {
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_upload_bytes: 20 * MIB,
};

function file(name: string, size = 1024) {
  return { name, size };
}

describe("extensionOf", () => {
  it.each([
    ["lecture.pdf", ".pdf"],
    ["Lecture.PDF", ".pdf"],
    ["notes.final.Md", ".md"],
    ["archive.tar.gz", ".gz"],
    [".md", ".md"],
    ["notes.md  ", ".md"],
    ["README", ""],
    ["notes.", ""],
    ["", ""],
  ])("reads %j as %j", (name, expected) => {
    expect(extensionOf(name)).toBe(expected);
  });
});

describe("checkFile", () => {
  it.each(["lecture.pdf", "notes.md", "syllabus.txt", "SCAN.PDF", "Notes.Md"])(
    "accepts %s",
    (name) => {
      expect(checkFile(file(name), RULES)).toBeNull();
    },
  );

  it.each(["timetable.docx", "photo.png", "README", "notes.", "lecture.pdf.zip"])(
    "turns down %s for its type",
    (name) => {
      expect(checkFile(file(name), RULES)).toBe("type");
    },
  );

  it("accepts a file of exactly the largest size", () => {
    expect(checkFile(file("lecture.pdf", 20 * MIB), RULES)).toBeNull();
  });

  it("turns down a file one byte over the largest size", () => {
    expect(checkFile(file("lecture.pdf", 20 * MIB + 1), RULES)).toBe("tooLarge");
  });

  it("turns down an empty file", () => {
    expect(checkFile(file("notes.md", 0), RULES)).toBe("empty");
  });

  it("names the type first when a file breaks more than one rule", () => {
    expect(checkFile(file("movie.mkv", 700 * MIB), RULES)).toBe("type");
    expect(checkFile(file("empty.docx", 0), RULES)).toBe("type");
  });

  it("follows the extensions the API allows", () => {
    const rules: FileRules = { ...RULES, allowed_extensions: [".md"] };

    expect(checkFile(file("lecture.pdf"), rules)).toBe("type");
    expect(checkFile(file("notes.md"), rules)).toBeNull();
  });
});

describe("acceptAttribute", () => {
  it("lists the allowed extensions for the file picker", () => {
    expect(acceptAttribute(RULES)).toBe(".pdf,.md,.txt");
  });
});

describe("listExtensions", () => {
  it("lists the allowed extensions for a sentence in either language", () => {
    expect(listExtensions(RULES, "en")).toBe(".pdf, .md, and .txt");
    expect(listExtensions(RULES, "ru")).toBe(".pdf, .md и .txt");
  });

  it("names a single extension on its own", () => {
    expect(listExtensions({ ...RULES, allowed_extensions: [".md"] }, "en")).toBe(".md");
  });
});
