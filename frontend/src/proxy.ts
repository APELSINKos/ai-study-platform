import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { routeDecision } from "@/features/auth/route-guard";

const SESSION_HINT_COOKIE = "recall_csrf";

// recall_access and recall_refresh are scoped to path /api and never reach page requests;
// recall_csrf is readable on every path, so its presence is the only session hint available here.
export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_HINT_COOKIE);
  const decision = routeDecision(pathname, search, hasSession);
  return decision.type === "redirect"
    ? NextResponse.redirect(new URL(decision.location, request.url))
    : NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next|.*\\..*).*)"],
};
