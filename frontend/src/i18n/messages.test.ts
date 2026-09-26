import { describe, expect, it } from "vitest";

import en from "../../messages/en.json";
import ru from "../../messages/ru.json";

function leaves(value: unknown, path = ""): Array<[string, unknown]> {
  if (typeof value !== "object" || value === null) {
    return [[path, value]];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    leaves(child, path ? `${path}.${key}` : key),
  );
}

describe("message catalogs", () => {
  it("define the same keys in every language", () => {
    const keys = (catalog: unknown) =>
      leaves(catalog)
        .map(([path]) => path)
        .sort();

    expect(keys(ru)).toEqual(keys(en));
  });

  it("contain no empty translations", () => {
    for (const [path, text] of [...leaves(en), ...leaves(ru)]) {
      expect(typeof text === "string" && text.trim().length > 0, path).toBe(true);
    }
  });
});
