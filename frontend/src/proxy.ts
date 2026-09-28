import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { routeDecision } from "@/features/auth/route-guard";

const SESSION_HINT_COOKIE = "recall_csrf";

// recall_access is scoped to /api and recall_refresh to /api/v1/auth, so neither ever
// reaches page requests; recall_csrf is readable on every path, so its presence is the
// only session hint available here. A failed refresh deletes it along with the other
// two cookies, so a stale hint cannot loop the user between /dashboard and /login.
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
