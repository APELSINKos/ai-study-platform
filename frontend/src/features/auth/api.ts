import { apiFetch } from "@/lib/api/client";
import type { LoginRequest, RegisterRequest, SessionOut, UserOut } from "@/lib/api/types";

export function fetchCurrentUser(): Promise<UserOut> {
  return apiFetch<UserOut>("/auth/me");
}

export function login(credentials: LoginRequest): Promise<SessionOut> {
  return apiFetch<SessionOut>("/auth/login", { method: "POST", json: credentials });
}

export function register(payload: RegisterRequest): Promise<SessionOut> {
  return apiFetch<SessionOut>("/auth/register", { method: "POST", json: payload });
}

export function logout(): Promise<void> {
  return apiFetch<void>("/auth/logout", { method: "POST" });
}
