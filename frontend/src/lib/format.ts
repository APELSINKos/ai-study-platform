const BYTES_PER_STEP = 1024;
const LARGER_BYTE_UNITS = ["kilobyte", "megabyte", "gigabyte"] as const;
const MS_PER_SECOND = 1000;
const SECONDS_PER_MINUTE = 60;
/** Shorter durations keep one decimal, so 1.4 seconds does not read as 1 second. */
const FRACTIONAL_SECONDS_BELOW = 10;

function formatUnit(locale: string, unit: string, value: number): string {
  return new Intl.NumberFormat(locale, {
    style: "unit",
    unit,
    unitDisplay: "short",
    maximumFractionDigits: 1,
  }).format(value);
}

function roundToTenth(value: number): number {
  return Math.round(value * 10) / 10;
}

/** A file size in 1024-based steps, the way the backend states its limits: 20 MiB reads as "20 MB". */
export function formatBytes(bytes: number, locale: string): string {
  if (bytes < BYTES_PER_STEP) {
    return new Intl.NumberFormat(locale, {
      style: "unit",
      unit: "byte",
      unitDisplay: "long",
    }).format(bytes);
  }
  let value = bytes;
  let unit: (typeof LARGER_BYTE_UNITS)[number] = LARGER_BYTE_UNITS[0];
  for (const candidate of LARGER_BYTE_UNITS) {
    value /= BYTES_PER_STEP;
    unit = candidate;
    // Without this a size just under the next step would read as "1,024 kB".
    if (roundToTenth(value) < BYTES_PER_STEP) {
      break;
    }
  }
  return formatUnit(locale, unit, value);
}

/** A processing time such as "44 ms", "1.2 sec" or "2 min 5 sec". */
export function formatDuration(ms: number, locale: string): string {
  const milliseconds = Math.round(ms);
  if (milliseconds < MS_PER_SECOND) {
    return formatUnit(locale, "millisecond", milliseconds);
  }
  const seconds = milliseconds / MS_PER_SECOND;
  if (seconds < FRACTIONAL_SECONDS_BELOW) {
    return formatUnit(locale, "second", seconds);
  }
  const totalSeconds = Math.round(seconds);
  if (totalSeconds < SECONDS_PER_MINUTE) {
    return formatUnit(locale, "second", totalSeconds);
  }
  const parts = [formatUnit(locale, "minute", Math.floor(totalSeconds / SECONDS_PER_MINUTE))];
  const restSeconds = totalSeconds % SECONDS_PER_MINUTE;
  if (restSeconds > 0) {
    parts.push(formatUnit(locale, "second", restSeconds));
  }
  return new Intl.ListFormat(locale, { type: "unit", style: "narrow" }).format(parts);
}
