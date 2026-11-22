import assert from "node:assert/strict";
import { test } from "node:test";
import { boot, type BootEnv } from "./boot.ts";

type Call = { url: string; init?: RequestInit };

/** A fetch stand-in that answers by URL from `routes` and records every call. */
function routedFetch(routes: Record<string, () => Response>): { fetchFn: typeof fetch; calls: Call[] } {
  const calls: Call[] = [];
  const fetchFn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    const route = routes[url];
    if (!route) throw new Error(`unexpected fetch ${url}`);
    return route();
  }) as typeof fetch;
  return { fetchFn, calls };
}

const json = (body: unknown, status = 200) => () => new Response(JSON.stringify(body), { status });

function memoryStore(initial: Record<string, string> = {}): BootEnv["store"] {
  const m = new Map(Object.entries(initial));
  return {
    getItem: (k) => m.get(k) ?? null,
    setItem: (k, v) => void m.set(k, v),
    removeItem: (k) => void m.delete(k),
  };
}

/** A BootEnv whose navigation calls are recorded. */
function env(href: string, fetchFn: typeof fetch, store = memoryStore()) {
  const replaced: string[] = [];
  const assigned: string[] = [];
  const e: BootEnv = {
    href,
    store,
    now: Date.UTC(2026, 10, 22),
    fetchFn,
    replaceUrl: (p) => void replaced.push(p),
    assign: (u) => void assigned.push(u),
  };
  return { e, replaced, assigned };
}

test("dev mode shows the dev user without a token", async () => {
  const { fetchFn, calls } = routedFetch({
    "/config.json": json({ authMode: "dev", apiBaseUrl: "" }),
    "/api/me": json({ email: "dev@localhost" }),
  });
  const { e, replaced, assigned } = env("http://localhost:5173/", fetchFn);
  assert.equal(await boot(e), "dev@localhost");
  const me = calls.find((c) => c.url === "/api/me");
  assert.equal(new Headers(me?.init?.headers).has("Authorization"), false);
  assert.deepEqual([replaced, assigned], [[], []]);
});

test("a bad config.json rejects", async () => {
  const { fetchFn } = routedFetch({ "/config.json": json({ authMode: "prod" }) });
  await assert.rejects(boot(env("http://localhost:5173/", fetchFn).e));
});
