import { API_BASE_URL } from "./apiClient.ts";

import type { AuditRef, ChatResponse, SourcePreview } from "../types/backend.ts";

export type ChatMetadataEvent = {
  type: "metadata";
  question: string;
  confidence: string;
  sources: SourcePreview[];
  audit: AuditRef | null;
  generation_provider: string | null;
  generation_model: string | null;
};

export type ChatTokenEvent = { type: "token"; text: string };
export type ChatDoneEvent = {
  type: "done";
  status: string;
  partial: boolean;
  message_id: number | null;
  assistant_message_id: number | null;
};
export type ChatErrorEvent = {
  type: "error";
  code?: string;
  message?: string;
};
export type ChatStreamEvent =
  | ChatMetadataEvent
  | ChatTokenEvent
  | ChatDoneEvent
  | ChatErrorEvent;

export class ChatStreamRequestError extends Error {
  readonly authenticationFailure: boolean;

  constructor(message: string, authenticationFailure = false) {
    super(message);
    this.name = "ChatStreamRequestError";
    this.authenticationFailure = authenticationFailure;
  }
}

export class StreamingUnsupportedError extends Error {}

export function deduplicateSources(sources: SourcePreview[]): SourcePreview[] {
  const seen = new Set<string>();
  return sources.filter((source) => {
    const key = source.id ?? [
      source.rank,
      source.kb_code,
      source.article_title,
      source.section_title,
      source.text,
    ].join("|");
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function normalizeChatStreamEvent(value: unknown): ChatStreamEvent | null {
  if (!isRecord(value) || typeof value.type !== "string") return null;
  if (value.type === "token" && typeof value.text === "string") {
    return { type: "token", text: value.text };
  }
  if (value.type === "done" && typeof value.status === "string" && typeof value.partial === "boolean") {
    return { type: "done", status: value.status, partial: value.partial,
      message_id: typeof value.message_id === "number" ? value.message_id : null,
      assistant_message_id: typeof value.assistant_message_id === "number" ? value.assistant_message_id : null };
  }
  if (value.type === "error") {
    return {
      type: "error",
      code: typeof value.code === "string" ? value.code : undefined,
      message: typeof value.message === "string" ? value.message : undefined,
    };
  }
  if (
    value.type === "metadata" &&
    typeof value.question === "string" &&
    typeof value.confidence === "string" &&
    Array.isArray(value.sources)
  ) {
    return {
      type: "metadata",
      question: value.question,
      confidence: value.confidence,
      sources: deduplicateSources(value.sources as SourcePreview[]),
      audit: isRecord(value.audit) ? (value.audit as AuditRef) : null,
      generation_provider:
        typeof value.generation_provider === "string" ? value.generation_provider : null,
      generation_model:
        typeof value.generation_model === "string" ? value.generation_model : null,
    };
  }
  return null;
}

export class NdjsonEventParser {
  private buffer = "";

  feed(text: string): ChatStreamEvent[] {
    this.buffer += text;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    return this.parseLines(lines);
  }

  finish(text = ""): ChatStreamEvent[] {
    this.buffer += text;
    const finalLine = this.buffer;
    this.buffer = "";
    return this.parseLines([finalLine]);
  }

  private parseLines(lines: string[]): ChatStreamEvent[] {
    const events: ChatStreamEvent[] = [];
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const event = normalizeChatStreamEvent(JSON.parse(line));
        if (event) events.push(event);
      } catch {
        // A malformed server line is isolated; later NDJSON events remain usable.
      }
    }
    return events;
  }
}

export function emptyStreamingResponse(question: string): ChatResponse {
  return {
    question,
    answer: "",
    confidence: "",
    sources: [],
    audit: null,
    generation_provider: "ollama",
    generation_model: null,
    generation_error: null,
  };
}

export async function streamKnowledgeBase(
  question: string,
  options: {
    token: string;
    sessionId?: number | null;
    signal: AbortSignal;
    onEvent: (event: ChatStreamEvent) => void;
    onAuthenticationFailure: () => void;
  },
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${options.token}`,
        "Content-Type": "application/json",
        Accept: "application/x-ndjson",
      },
      body: JSON.stringify({ question, ...(options.sessionId ? { session_id: options.sessionId } : {}) }),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ChatStreamRequestError("Le service est momentanément indisponible.");
  }

  if (response.status === 401) {
    options.onAuthenticationFailure();
    throw new ChatStreamRequestError("Votre session a expiré.", true);
  }
  if (!response.ok) {
    throw new ChatStreamRequestError("La réponse n’a pas pu être générée.");
  }
  if (!response.body) throw new StreamingUnsupportedError();

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const parser = new NdjsonEventParser();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of parser.feed(decoder.decode(value, { stream: true }))) {
        options.onEvent(event);
      }
    }
    for (const event of parser.finish(decoder.decode())) options.onEvent(event);
  } finally {
    reader.releaseLock();
  }
}
