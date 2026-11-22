import assert from "node:assert/strict";
import { test } from "node:test";
import { boot, type BootEnv } from "./boot.ts";
import { COGNITO, NOW, NOW_SEC, TOKEN_URL, json, jwt, memoryStore, routedFetch } from "./test-helpers.ts";

/** A BootEnv whose navigation calls are recorded. */
function env(href: string, fetchFn: typeof fetch, store = memoryStore()) {
  const replaced: string[] = [];
  const assigned: string[] = [];
  const e: BootEnv = {
    href,
    store,
    now: NOW,
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

test("successful callback end to end", async () => {
  const idToken = jwt({ email: "person@example.com", exp: NOW_SEC + 3600 });
  const { fetchFn, calls } = routedFetch({
    "/config.json": json(COGNITO),
    [TOKEN_URL]: json({ id_token: idToken, expires_in: 3600 }),
    "https://api.example/api/me": json({ email: "person@example.com" }),
  });
  const store = memoryStore({ pkce_state: "S", pkce_verifier: "V" });
  const { e, replaced, assigned } = env("https://app.example/?code=abc&state=S", fetchFn, store);

  assert.equal(await boot(e), "person@example.com");
  const me = calls.find((c) => c.url === "https://api.example/api/me");
  assert.equal(new Headers(me?.init?.headers).get("Authorization"), `Bearer ${idToken}`);
  assert.deepEqual(replaced, ["/"]);
  assert.deepEqual(assigned, []);
});

test("callback failure still cleans the URL", async () => {
  const { fetchFn } = routedFetch({ "/config.json": json(COGNITO) });
  const { e, replaced, assigned } = env(
    "https://app.example/?error=access_denied&error_description=User+cancelled",
    fetchFn,
  );
  await assert.rejects(boot(e), /User cancelled/);
  assert.deepEqual(replaced, ["/"]);
  assert.deepEqual(assigned, []);
});

test("no session redirects to the Hosted UI", async () => {
  const { fetchFn, calls } = routedFetch({ "/config.json": json(COGNITO) });
  const { e, assigned } = env("https://app.example/", fetchFn);
  assert.equal(await boot(e), null);
  assert.equal(assigned.length, 1);
  assert.ok(assigned[0].startsWith(`${COGNITO.cognitoDomainUrl}/oauth2/authorize?`));
  assert.equal(calls.some((c) => c.url.endsWith("/api/me")), false);
});
