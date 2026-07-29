import assert from "node:assert/strict";
import test from "node:test";

import {
  ChatStreamRequestError,
  NdjsonEventParser,
  StreamingUnsupportedError,
  deduplicateSources,
  streamKnowledgeBase,
  type ChatStreamEvent,
} from "../src/services/chatStream.ts";
import { askKnowledgeBase } from "../src/services/chatApi.ts";

const encoder = new TextEncoder();
function streamFrom(chunks: Uint8Array[], failure?: Error): ReadableStream<Uint8Array> {
  return new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(chunk);
    if (failure) controller.error(failure); else controller.close();
  }});
}
async function withFetch(response: Response | ((signal: AbortSignal) => Promise<Response>), callback: () => Promise<void>) {
  const original = globalThis.fetch;
  globalThis.fetch = ((_input, init) => typeof response === "function"
    ? response(init?.signal as AbortSignal) : Promise.resolve(response)) as typeof fetch;
  try { await callback(); } finally { globalThis.fetch = original; }
}
function source(id: string) { return {
  rank: 1, score: 0.9, id, kb_code: "KB", article_title: "Article",
  section_title: "Section", chunk_type: "text", priority: null, text: "Texte",
}; }

test("normal metadata and token streaming, with multiple events in one chunk", async () => {
  const events: ChatStreamEvent[] = [];
  const body = [
    JSON.stringify({ type: "metadata", question: "Q", confidence: "high", sources: [source("1")], audit: null, generation_provider: "ollama", generation_model: "3b" }),
    JSON.stringify({ type: "token", text: "Bon" }),
    JSON.stringify({ type: "token", text: "jour" }),
    JSON.stringify({ type: "done", status: "complete", partial: false }),
  ].join("\n") + "\n";
  await withFetch(new Response(streamFrom([encoder.encode(body)]), { status: 200 }), async () => {
    await streamKnowledgeBase("Q", { token: "token", signal: new AbortController().signal,
      onEvent: (event) => events.push(event), onAuthenticationFailure: () => assert.fail() });
  });
  assert.deepEqual(events.map((event) => event.type), ["metadata", "token", "token", "done"]);
  assert.equal(events.filter((event) => event.type === "token").map((event) => event.text).join(""), "Bonjour");
});

test("UTF-8 split boundaries and incomplete lines are buffered", async () => {
  const encoded = encoder.encode(JSON.stringify({ type: "token", text: "été 🚀" }) + "\n");
  const split = encoded.indexOf(0xc3) + 1;
  const events: ChatStreamEvent[] = [];
  await withFetch(new Response(streamFrom([encoded.slice(0, split), encoded.slice(split)])), async () => {
    await streamKnowledgeBase("Q", { token: "token", signal: new AbortController().signal,
      onEvent: (event) => events.push(event), onAuthenticationFailure: () => assert.fail() });
  });
  assert.equal(events[0]?.type, "token");
  assert.equal((events[0] as { text: string }).text, "été 🚀");
});

test("malformed and blank lines are ignored without losing later events", () => {
  const parser = new NdjsonEventParser();
  assert.deepEqual(parser.feed("\nnot-json\n{\"type\":\"token\",\"text\":\"ok\"}\n"), [{ type: "token", text: "ok" }]);
});

test("incomplete final line is parsed on finish", () => {
  const parser = new NdjsonEventParser();
  assert.deepEqual(parser.feed('{"type":"token","text":"later"'), []);
  assert.deepEqual(parser.finish("}"), [{ type: "token", text: "later" }]);
});

test("cancellation aborts the request", async () => {
  const controller = new AbortController();
  await withFetch((signal) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("", "AbortError")));
  }), async () => {
    const request = streamKnowledgeBase("Q", { token: "token", signal: controller.signal,
      onEvent: () => assert.fail(), onAuthenticationFailure: () => assert.fail() });
    controller.abort();
    await assert.rejects(request, (error: unknown) => error instanceof DOMException && error.name === "AbortError");
  });
});

test("partial stream failure keeps already delivered token events", async () => {
  const events: ChatStreamEvent[] = [];
  let read = 0;
  const partialStream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (read++ === 0) controller.enqueue(encoder.encode('{"type":"token","text":"partiel"}\n'));
      else controller.error(new Error("network"));
    },
  });
  await withFetch(new Response(partialStream), async () => {
    await assert.rejects(streamKnowledgeBase("Q", { token: "token", signal: new AbortController().signal,
      onEvent: (event) => events.push(event), onAuthenticationFailure: () => assert.fail() }));
  });
  assert.deepEqual(events, [{ type: "token", text: "partiel" }]);
});

test("authentication failure invokes existing session handler", async () => {
  let loggedOut = 0;
  await withFetch(new Response(null, { status: 401 }), async () => {
    await assert.rejects(streamKnowledgeBase("Q", { token: "expired", signal: new AbortController().signal,
      onEvent: () => assert.fail(), onAuthenticationFailure: () => { loggedOut += 1; } }),
      (error: unknown) => error instanceof ChatStreamRequestError && error.authenticationFailure);
  });
  assert.equal(loggedOut, 1);
});

test("duplicate sources are removed and events are not duplicated", () => {
  assert.equal(deduplicateSources([source("same"), source("same")]).length, 1);
  const parser = new NdjsonEventParser();
  assert.equal(parser.feed('{"type":"token","text":"once"}\n').length, 1);
  assert.equal(parser.finish().length, 0);
});

test("missing readable body reports fallback compatibility and legacy API remains exported", async () => {
  assert.equal(typeof askKnowledgeBase, "function");
  await withFetch({ ok: true, status: 200, body: null } as Response, async () => {
    await assert.rejects(streamKnowledgeBase("Q", { token: "token", signal: new AbortController().signal,
      onEvent: () => assert.fail(), onAuthenticationFailure: () => assert.fail() }), StreamingUnsupportedError);
  });
});
