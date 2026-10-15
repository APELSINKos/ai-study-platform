import { describe, expect, it } from "vitest";

import { formatBytes, formatDuration } from "./format";

const KIB = 1024;
const MIB = 1024 * KIB;
const GIB = 1024 * MIB;

describe("formatBytes", () => {
  it.each([
    [0, "0 bytes"],
    [1, "1 byte"],
    [1000, "1,000 bytes"],
    [1023, "1,023 bytes"],
    [KIB, "1 kB"],
    [1536, "1.5 kB"],
    [1_000_000, "976.6 kB"],
    [MIB - 1, "1 MB"],
    [20 * MIB, "20 MB"],
    [20 * MIB + 400 * KIB, "20.4 MB"],
    [GIB, "1 GB"],
  ])("formats %i bytes in English as %s", (bytes, expected) => {
    expect(formatBytes(bytes, "en")).toBe(expected);
  });

  it.each([
    [1, "1 байт"],
    [2, "2 байта"],
    [5, "5 байт"],
    [1536, "1,5 кБ"],
    [20 * MIB, "20 МБ"],
    [GIB, "1 ГБ"],
  ])("formats %i bytes in Russian as %s", (bytes, expected) => {
    expect(formatBytes(bytes, "ru")).toBe(expected);
  });
});

describe("formatDuration", () => {
  it.each([
    [0, "0 ms"],
    [44, "44 ms"],
    [999, "999 ms"],
    [1000, "1 sec"],
    [1234, "1.2 sec"],
    [12_345, "12 sec"],
    [59_499, "59 sec"],
    [59_500, "1 min"],
    [125_000, "2 min 5 sec"],
    [600_000, "10 min"],
  ])("formats %i ms in English as %s", (ms, expected) => {
    expect(formatDuration(ms, "en")).toBe(expected);
  });

  it.each([
    [44, "44 мс"],
    [1234, "1,2 с"],
    [12_345, "12 с"],
    [125_000, "2 мин 5 с"],
    [600_000, "10 мин"],
  ])("formats %i ms in Russian as %s", (ms, expected) => {
    expect(formatDuration(ms, "ru")).toBe(expected);
  });
});
