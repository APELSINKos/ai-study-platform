import type { components } from "./schema";

export type Schemas = components["schemas"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type UserOut = Schemas["UserOut"];
export type SessionOut = Schemas["SessionOut"];
export type RegisterRequest = Schemas["RegisterRequest"];
export type LoginRequest = Schemas["LoginRequest"];
