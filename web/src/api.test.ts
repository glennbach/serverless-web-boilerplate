import assert from "node:assert/strict";
import { test } from "node:test";
import { fetchEmail, parseMe } from "./api.ts";

type Call = { url: string; headers: Headers };

/** A fetch stand-in that records each call and answers with one response. */
function fakeFetch(status: number, body: unknown): { fetchFn: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), headers: new Headers(init?.headers) });
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch;
  return { fetchFn, calls };
}

test("parseMe accepts a nonempty email", () => {
  assert.equal(parseMe({ email: "a@b.c" }), "a@b.c");
});

test("parseMe rejects anything else", () => {
  for (const body of [null, "x", [], {}, { email: "" }, { email: 5 }]) {
    assert.throws(() => parseMe(body), Error, JSON.stringify(body));
  }
});

test("fetchEmail joins the base URL and /api/me", async () => {
  const cases: [string, string][] = [
    ["", "/api/me"],
    ["https://x.example/", "https://x.example/api/me"],
    ["https://x.example", "https://x.example/api/me"],
  ];
  for (const [base, want] of cases) {
    const { fetchFn, calls } = fakeFetch(200, { email: "a@b.c" });
    await fetchEmail(base, null, fetchFn);
    assert.equal(calls[0].url, want);
  }
});

test("fetchEmail sends Authorization only with a token", async () => {
  const withToken = fakeFetch(200, { email: "a@b.c" });
  await fetchEmail("", "t", withToken.fetchFn);
  assert.equal(withToken.calls[0].headers.get("Authorization"), "Bearer t");

  const without = fakeFetch(200, { email: "a@b.c" });
  await fetchEmail("", null, without.fetchFn);
  assert.equal(without.calls[0].headers.has("Authorization"), false);
});

test("fetchEmail rejects a non-2xx response with its status", async () => {
  await assert.rejects(fetchEmail("", null, fakeFetch(401, "unauthorized").fetchFn), /401/);
});

test("fetchEmail rejects a body without email", async () => {
  await assert.rejects(fetchEmail("", null, fakeFetch(200, { name: "x" }).fetchFn));
});
