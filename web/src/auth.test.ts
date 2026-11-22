import assert from "node:assert/strict";
import { test } from "node:test";
import { authorizeUrl, codeChallenge, idTokenExpiry, randomString, signIn } from "./auth.ts";
import { COGNITO as cfg, NOW, NOW_SEC, TOKEN_URL, json, jwt, memoryStore, routedFetch } from "./test-helpers.ts";

const APP = "https://app.example/";

test("codeChallenge matches RFC 7636 Appendix B", async () => {
  assert.equal(
    await codeChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
    "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
  );
});

test("randomString is 32 random bytes in base64url", () => {
  const a = randomString();
  assert.match(a, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(a, randomString());
});

test("authorizeUrl carries every Hosted UI parameter", () => {
  const u = new URL(authorizeUrl(cfg, APP, "CH", "ST"));
  assert.equal(u.origin + u.pathname, `${cfg.cognitoDomainUrl}/oauth2/authorize`);
  assert.deepEqual(Object.fromEntries(u.searchParams), {
    response_type: "code",
    client_id: "client123",
    redirect_uri: APP,
    scope: "openid email",
    state: "ST",
    code_challenge_method: "S256",
    code_challenge: "CH",
  });
});

test("idTokenExpiry reads exp in milliseconds", () => {
  assert.equal(idTokenExpiry(jwt({ exp: 1795000000 })), 1795000000000);
  for (const bad of ["not-a-jwt", jwt({}), jwt({ exp: "x" })]) {
    assert.throws(() => idTokenExpiry(bad), Error, bad);
  }
});

test("no session redirects with stored state and verifier", async () => {
  const store = memoryStore();
  const { fetchFn, calls } = routedFetch({});
  const r = await signIn(cfg, new URL(APP), store, NOW, fetchFn);
  assert.ok("redirectTo" in r);
  const u = new URL(r.redirectTo);
  assert.equal(u.searchParams.get("state"), store.getItem("pkce_state"));
  assert.equal(u.searchParams.get("code_challenge"), await codeChallenge(store.getItem("pkce_verifier")!));
  assert.equal(calls.length, 0);
});

test("callback exchanges the code and keeps the ID token's own expiry", async () => {
  const store = memoryStore({ pkce_state: "S", pkce_verifier: "V" });
  // ID token lives 5 minutes; expires_in (the access token) says 1 hour.
  const idToken = jwt({ email: "person@example.com", exp: NOW_SEC + 300 });
  const { fetchFn, calls } = routedFetch({ [TOKEN_URL]: json({ id_token: idToken, expires_in: 3600 }) });

  const r = await signIn(cfg, new URL(`${APP}?code=abc&state=S`), store, NOW, fetchFn);

  assert.deepEqual(r, { idToken });
  assert.equal(calls.length, 1);
  const init = calls[0].init!;
  assert.equal(init.method, "POST");
  const headers = new Headers(init.headers);
  assert.equal(headers.get("Content-Type"), "application/x-www-form-urlencoded");
  assert.equal(headers.has("Authorization"), false);
  assert.deepEqual(Object.fromEntries(new URLSearchParams(String(init.body))), {
    grant_type: "authorization_code",
    client_id: "client123",
    code: "abc",
    code_verifier: "V",
    redirect_uri: APP,
  });
  assert.deepEqual(JSON.parse(store.getItem("session")!), { idToken, expiresAt: (NOW_SEC + 300) * 1000 });
  assert.equal(store.has("pkce_state") || store.has("pkce_verifier"), false);
});

test("state mismatch rejects without calling the token endpoint", async () => {
  const store = memoryStore({ pkce_state: "S", pkce_verifier: "V" });
  const { fetchFn, calls } = routedFetch({});
  await assert.rejects(signIn(cfg, new URL(`${APP}?code=abc&state=EVIL`), store, NOW, fetchFn));
  assert.equal(calls.length, 0);
});

test("callback with no stored state rejects without calling the token endpoint", async () => {
  const { fetchFn, calls } = routedFetch({});
  await assert.rejects(signIn(cfg, new URL(`${APP}?code=abc&state=S`), memoryStore(), NOW, fetchFn));
  assert.equal(calls.length, 0);
});

test("a Hosted UI error is shown, not retried", async () => {
  const { fetchFn } = routedFetch({});
  const url = new URL(`${APP}?error=access_denied&error_description=User+cancelled`);
  await assert.rejects(signIn(cfg, url, memoryStore(), NOW, fetchFn), /User cancelled/);
});

test("a valid session is reused", async () => {
  const session = JSON.stringify({ idToken: "tok", expiresAt: NOW + 10 * 60_000 });
  const { fetchFn, calls } = routedFetch({});
  assert.deepEqual(await signIn(cfg, new URL(APP), memoryStore({ session }), NOW, fetchFn), { idToken: "tok" });
  assert.equal(calls.length, 0);
});

test("a session within 60 s of expiry forces sign-in", async () => {
  const session = JSON.stringify({ idToken: "tok", expiresAt: NOW + 30_000 });
  const r = await signIn(cfg, new URL(APP), memoryStore({ session }), NOW, routedFetch({}).fetchFn);
  assert.ok("redirectTo" in r);
});

test("token endpoint failures reject", async () => {
  const responses = [json({ error: "invalid_grant" }, 400), json({ access_token: "a" }), json({ id_token: "garbage" })];
  for (const res of responses) {
    const store = memoryStore({ pkce_state: "S", pkce_verifier: "V" });
    const { fetchFn } = routedFetch({ [TOKEN_URL]: res });
    await assert.rejects(signIn(cfg, new URL(`${APP}?code=abc&state=S`), store, NOW, fetchFn));
  }
});
