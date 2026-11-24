import type { components } from "./schema";

export type Schemas = components["schemas"];
export type ReadinessResponse = Schemas["ReadinessResponse"];
export type UserOut = Schemas["UserOut"];
export type SessionOut = Schemas["SessionOut"];
export type RegisterRequest = Schemas["RegisterRequest"];
export type LoginRequest = Schemas["LoginRequest"];

export type WorkspaceOut = Schemas["WorkspaceOut"];
export type WorkspacePage = Schemas["WorkspacePage"];
export type WorkspaceStats = Schemas["WorkspaceStats"];
export type WorkspaceCreateRequest = Schemas["WorkspaceCreateRequest"];
export type WorkspaceUpdateRequest = Schemas["WorkspaceUpdateRequest"];

export type DocumentOut = Schemas["DocumentOut"];
export type DocumentPage = Schemas["DocumentPage"];
export type DocumentStatus = Schemas["DocumentStatus"];
export type DocumentErrorCode = Schemas["DocumentErrorCode"];
export type DocumentContentType = Schemas["DocumentContentType"];
export type Difficulty = Schemas["Difficulty"];
export type ChunkOut = Schemas["ChunkOut"];
export type ChunkPage = Schemas["ChunkPage"];

export type SearchResults = Schemas["SearchResults"];
export type SearchHit = Schemas["SearchHit"];
export type SnippetPart = Schemas["SnippetPart"];
export type MatchKind = Schemas["MatchKind"];

export type ChatSessionOut = Schemas["ChatSessionOut"];
export type ChatSessionDetailOut = Schemas["ChatSessionDetailOut"];
export type ChatSessionPage = Schemas["ChatSessionPage"];
export type ChatMessageOut = Schemas["ChatMessageOut"];
export type ChatMessageRole = Schemas["ChatMessageRole"];
export type CitationOut = Schemas["CitationOut"];
export type ChatTurnOut = Schemas["ChatTurnOut"];
export type ChatSessionCreateRequest = Schemas["ChatSessionCreateRequest"];
export type ChatSessionUpdateRequest = Schemas["ChatSessionUpdateRequest"];
export type ChatMessageCreateRequest = Schemas["ChatMessageCreateRequest"];

export type MetaOut = Schemas["MetaOut"];
export type ChatInfo = Schemas["ChatInfo"];
export type AiInfo = Schemas["AiInfo"];
export type AiMode = Schemas["AiMode"];
