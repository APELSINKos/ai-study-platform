import { apiFetch } from "@/lib/api/client";
import type { MetaOut } from "@/lib/api/types";

export function fetchMeta(): Promise<MetaOut> {
  return apiFetch<MetaOut>("/meta");
}
